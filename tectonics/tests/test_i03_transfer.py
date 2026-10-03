"""Focused I03.2 checks: move the network over one accepted interval and transfer complete material.

Declared sector worlds only, moved by supplied finite rotations (prescribed_history_v1). The checks are the brief's:
a stationary state and a whole-sphere rigid rotation transfer nothing and reset no age; one plate rotating between
fixed neighbours balances area, reference mass, phase volume and signed enthalpy exactly; the same holds in rotated
coordinates, across the frame's seam and poles; a mesh change without motion; the I01 D3 staged lune (exact areas,
birth-time intervals and the 4.0 against 4.2 Myr trajectory age); a supplied trench with exhaustion refused; a stale
overlap map refused; and the declared resource caps. Every control value and tolerance is read from
cases/i03_controls_v1.json; the tolerances are the existing W01/W02/I01 ones and none is new.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import replace
from fractions import Fraction
import json
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics import integration_ledger as L, integration_sphere as S, integration_state as I
from atlas_tectonics import integration_transfer as T
from atlas_tectonics import resources
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import GeometryLimits
from atlas_tectonics.kinematics import Rotation
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F

RELATIVE = F.tolerance('relative')                              # 1e-12, existing
ANGULAR = F.tolerance('angular_absolute_rad')                   # 2e-12, existing
AREA_CLOSURE_SR = F.tolerance('area_closure_absolute_sr')       # 2e-11, existing
BAND = F.tolerance('attachment_band_rad')                       # 64 eps, existing
ALGEBRA = F.tolerance('junction_algebra_relative')              # 1e-11, existing
D3 = F.D3
R = F.RADIUS_M
SPHERE_M2 = F.SPHERE_M2
MYR = F.MYR_S
LUNE = F.control('d3_lune')['expects']
ONE = F.control('one_plate')
TURN = ONE['rotation_deg']
REFUSALS = F.control('motion_refusals')
RESOURCES = F.CASE['resources']
lune = F.lune


def close(test, value, expected, relative=RELATIVE):
    test.assertLessEqual(abs(value-expected), relative*abs(expected), (value, expected))


def exact(material, account):
    """One exact account of a material's stored record ('initial', 'rounding' or 'allowance'), per column."""
    return [Fraction(text) for text in material.descriptor()['exact'][account]]


def declared_and_supplied(material):
    """Per column: the stored pieces' exact total less the exact rounding, which is declared plus supplied."""
    return [material.exact_total(column)-rounding
            for column, rounding in zip(material.columns, exact(material, 'rounding'))]


def still(network, start=0, end=1, **changes):
    values = dict(start_step=start, end_step=end, rotations={plate: F.IDENTITY for plate in network.plate_ids})
    values.update(changes)
    return T.Motion(**values)


def lune_motion(step, east, west, tilt=None, **changes):
    values = dict(start_step=step, end_step=step+1,
                  rotations={'east': F.spin(east, tilt), 'west': F.spin(west, tilt)},
                  supplies=F.both_sides('boundary-m00'), sinks=(F.sink('boundary-m04'),))
    values.update(changes)
    return T.Motion(**values)


def stage_rotations(index):
    """(east, west) rotations in degrees of one D3 stage: the ridge moves at the mean of its two plates."""
    duration, fast, axis = D3['stages_Myr'][index], D3['plate_deg_per_Myr'][index], D3['ridge_deg_per_Myr'][index]
    return fast*duration, (2*axis-fast)*duration


def staged_lune(tilt=None, budget=None, **changes):
    """The I01 D3 staged history on a closed sphere: (the states from the start, the steps)."""
    state = F.crust(F.lune_world(tilt=tilt), **changes)
    states, steps, now = [state], [], 0.
    for index, duration in enumerate(D3['stages_Myr']):
        east, west = stage_rotations(index)
        now += duration*MYR
        step = T.advance(states[-1], lune_motion(index, east, west, tilt), end_time_s=now, budget=budget)
        steps.append(step)
        states.append(step.state)
    return states, steps


def strips(state, boundary, side, step):
    prefix = '%s|%s|%d|' % (boundary, side, step)
    return [face_id for face_id in state.network.face_ids if face_id.startswith(prefix)]


def longitudes(state, face_id, tilt=None):
    """Longitudes about the world axis of a face's vertices, without the poles (whose longitude is arbitrary)."""
    lookup = {name: i for i, name in enumerate(state.network.vertex_ids)}
    ring = [name for name in state.network.face(face_id).vertex_ids if name not in ('N', 'S')]
    return F.longitude_deg(state.network.vertex_direction[[lookup[name] for name in ring]], tilt)


class StationaryAndRigidTests(unittest.TestCase):
    def test_stationary_state_is_the_identity_map_without_any_transfer(self):
        end = F.control('stationary')['end_time_s']
        state = F.crust(F.lune_world())
        step = T.advance(state, still(state.network), end_time_s=end)
        after = step.state
        self.assertEqual((step.map.rows, step.map.mesh_rows, step.stock_transfers), ((), (), ()))
        self.assertEqual(after.material.stock.tobytes(), state.material.stock.tobytes())
        self.assertEqual(after.material.piece_face.tobytes(), state.material.piece_face.tobytes())
        self.assertEqual(after.network.vertex_direction.tobytes(), state.network.vertex_direction.tobytes())
        self.assertEqual(after.network.face_ids, state.network.face_ids)
        self.assertEqual(after.material.supplied(), {})
        summary = step.summary()
        self.assertEqual((summary['map']['rows'], summary['map']['born_faces'], summary['map']['consumed_faces'],
                          summary['map']['carried_faces']), (0, 0, 0, len(state.network.face_ids)))
        self.assertEqual({b['status'] for b in summary['boundaries']}, {T.LOCKED})
        # Only time, step and lineage changed; the state is a computed successor of its parent.
        self.assertEqual((after.time_s, after.step, after.issued_by), (end, 1, I.COMPUTED))
        self.assertEqual((after.parent_state_id, after.initial_state_id), (state.state_id, state.state_id))
        self.assertEqual(after.network.lineage.parent_network_id, state.network.network_id)
        self.assertEqual(after.network.atlas.geometry_id, state.network.atlas.geometry_id)
        self.assertEqual(after.material.cohorts, state.material.cohorts)
        self.assertEqual(state.step, 0)                                        # the parent is never changed

    def test_whole_sphere_rigid_rotation_moves_everything_and_transfers_nothing(self):
        control = F.control('rigid_rotation')
        formed, (first, second) = control['inherited_east_formed_myr']*MYR, control['interval_end_myr']
        dated = (F.cohort('inherited-east', start=formed, end=formed), F.cohort('inherited-west'))
        state = F.crust(F.lune_world(tilt=F.TILT), cohorts=dated)
        turn = F.rotation(control['rotation'])
        motion = still(state.network, rotations={'east': turn, 'west': turn})
        step = T.advance(state, motion, end_time_s=first*MYR)
        after = step.state
        self.assertEqual(step.map.rows, ())
        self.assertEqual(step.summary()['attachment_rad'], 0.)       # every plate's own vertex is the boundary's
        self.assertEqual(after.material.stock.tobytes(), state.material.stock.tobytes())     # no heat, no material
        self.assertEqual(after.material.cohorts, state.material.cohorts)                     # no age reset
        age = first*MYR-formed
        self.assertEqual(after.material.ages_s(first*MYR)['inherited-east'], (age, age))
        self.assertIsNone(after.material.ages_s(first*MYR)['inherited-west'])
        self.assertLessEqual(float(np.max(F.angle(after.network.vertex_direction,
                                                  turn.apply(state.network.vertex_direction)))), ANGULAR)
        # No deformation: every face keeps its measure, adjacency and owner.
        np.testing.assert_allclose(after.network.face_area_m2, state.network.face_area_m2, rtol=RELATIVE, atol=0)
        self.assertEqual(after.network.face_ids, state.network.face_ids)
        self.assertEqual(after.network.adjacency(), state.network.adjacency())
        self.assertEqual([(j.vertex_id, j.plate_ids, j.boundary_ends) for j in after.network.junctions],
                         [(j.vertex_id, j.plate_ids, j.boundary_ends) for j in state.network.junctions])
        self.assertLessEqual(abs(after.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
        for plate in ('east', 'west'):
            self.assertLessEqual(F.rotation_angle(after.network.plate(plate).rotation, turn), ANGULAR)
        self.assertTrue(after.material.closure()['identity_exact'])
        # A second step composes the total rotation; nothing drifts into a transfer.
        again = T.advance(after, still(after.network, 1, 2, rotations={'east': turn, 'west': turn}),
                          end_time_s=second*MYR).state
        self.assertEqual(again.material.stock.tobytes(), state.material.stock.tobytes())
        self.assertLessEqual(F.rotation_angle(again.network.plate('east').rotation, turn.then(turn)), ANGULAR)
        # A plate that already carries a total rotation composes the stage after it: R_total = R_stage R_prior.
        prior = F.rotation(control['prior_rotation'])
        turned = F.crust(F.lune_world(tilt=F.TILT, rotations={'east': prior, 'west': prior}), cohorts=dated)
        total = T.advance(turned, motion, end_time_s=first*MYR).state.network.plate('east').rotation
        self.assertLessEqual(F.rotation_angle(total, prior.then(turn)), ANGULAR)
        self.assertGreater(F.rotation_angle(total, turn.then(prior)), ANGULAR)        # the order is this one
        probe = np.array(F.direction(*control['probe_direction_deg']))
        self.assertLessEqual(float(F.angle(total.apply(probe), turn.apply(prior.apply(probe)))), ANGULAR)

    def test_rotating_one_vertex_or_all_of_them_gives_the_same_bits(self):
        # A boundary vertex is moved alone by its record's rule and a plate's vertices are moved together. Both
        # must land on the same bits, or a locked boundary would not stay exactly attached and a restored step
        # would not reproduce its geometry. A library matrix product does not promise that across batch sizes.
        network = F.lune_world(tilt=F.TILT)
        turn = F.rotation(F.control('rigid_rotation')['rotation'])
        points = network.vertex_direction
        together = T._turned(turn, points)
        for index in range(len(points)):
            self.assertEqual(T._turned(turn, points[index]).tobytes(), together[index:index+1].tobytes(), index)
        self.assertLessEqual(float(np.max(F.angle(together, turn.apply(points)))), ANGULAR)

    def test_supply_or_sink_for_a_boundary_that_does_nothing_is_refused(self):
        state = F.crust(F.lune_world())
        for extra in (dict(supplies=F.both_sides('boundary-m00')), dict(sinks=(F.sink('boundary-m04'),))):
            with self.assertRaises(T.TransferRefused) as caught:
                T.advance(state, still(state.network, **extra), end_time_s=F.control('stationary')['end_time_s'])
            self.assertIn('nothing in this interval', str(caught.exception))


class LuneTests(unittest.TestCase):
    """The I01 D3 staged moving-ridge lune, on real faces of a closed sphere with a trench on the far side."""

    @classmethod
    def setUpClass(cls):
        cls.states, cls.steps = staged_lune()
        cls.end = sum(D3['stages_Myr'])*MYR

    def test_birth_areas_are_the_exact_lunes(self):
        material = self.states[-1].material
        supplied = material.supplied()
        # Each side receives (plate - ridge) rate times duration: 3 and 3.75 degrees of longitude, 6.75 in all.
        expected = [(p-r)*d for p, r, d in zip(D3['plate_deg_per_Myr'], D3['ridge_deg_per_Myr'], D3['stages_Myr'])]
        self.assertEqual(expected, LUNE['born_per_side_deg'])
        self.assertEqual(sum(expected), LUNE['born_per_side_total_deg'])
        for side in S.SIDES:
            close(self, float(supplied['ridge|boundary-m00|'+side]['area_m2']), lune(sum(expected)))
        for index, degrees in enumerate(expected):
            state = self.states[index+1]
            lookup = {name: i for i, name in enumerate(state.network.face_ids)}
            for side in S.SIDES:
                born = strips(state, 'boundary-m00', side, index+1)
                self.assertEqual(len(born), LUNE['born_faces_per_stage']//2)      # one face per ridge segment
                close(self, math.fsum(float(state.network.face_area_m2[lookup[f]]) for f in born), lune(degrees))
        # The exact area account of each ridge side is the exact sum of its born faces' areas, as measured in the
        # accepted state each was born into.
        booked = Fraction(0)
        for index in (1, 2):
            state = self.states[index]
            lookup = {name: i for i, name in enumerate(state.network.face_ids)}
            booked += sum((Fraction(float(state.network.face_area_m2[lookup[f]]))
                           for f in strips(state, 'boundary-m00', 'right', index)), Fraction(0))
        self.assertEqual(supplied['ridge|boundary-m00|right']['area_m2'], booked)

    def test_birth_time_intervals_follow_the_accepted_intervals(self):
        material = self.states[-1].material
        cohorts = [material.cohort('boundary-m00|right|0-1'), material.cohort('boundary-m00|right|1-2')]
        self.assertEqual([[c.formation_start_s, c.formation_end_s] for c in cohorts],
                         [[start*MYR, end*MYR] for start, end in LUNE['cohort_formation_myr']])
        ages = material.ages_s(self.end)
        self.assertEqual([[a/MYR for a in ages[c.cohort_id]] for c in cohorts], LUNE['cohort_ages_at_end_myr'])
        self.assertEqual((cohorts[0].material_id, cohorts[0].origin_id),
                         ('declared-new-crust', F.SOURCE+'#ridge-supply'))
        # Inherited material keeps its unknown formation: nothing was assigned an age.
        self.assertIsNone(ages['inherited-east'])
        self.assertIsNone(ages['inherited-west'])
        # A face born in an interval holds exactly that interval's cohort.
        final = self.states[-1]
        for face_id in strips(final, 'boundary-m00', 'right', 1):
            self.assertEqual(final.material.face_cohorts(face_id), ('boundary-m00|right|0-1',))

    def test_age_follows_the_trajectory_not_the_distance_to_the_present_ridge(self):
        final = self.states[-1]
        resolved = math.degrees(ANGULAR)
        # Stage-1 crust on the eastern plate was born between 1 and 4 degrees and then rode 3 degrees east.
        first = np.concatenate([longitudes(final, f) for f in strips(final, 'boundary-m00', 'right', 1)])
        second = np.concatenate([longitudes(final, f) for f in strips(final, 'boundary-m00', 'right', 2)])
        for values, (low, high) in ((first, LUNE['stage_1_strip_longitudes_deg']),
                                    (second, LUNE['stage_2_strip_longitudes_deg'])):
            self.assertLessEqual(abs(values.min()-low), resolved)
            self.assertLessEqual(abs(values.max()-high), resolved)
        midpoint = (first.min()+first.max())/2
        ridge = second.min()
        self.assertLessEqual(abs(midpoint-LUNE['stage_1_midpoint_deg']), resolved)
        ages = final.material.ages_s(self.end)['boundary-m00|right|0-1']
        actual = (ages[0]+ages[1])/2/MYR
        self.assertEqual(actual, LUNE['trajectory_mean_age_myr'])
        # Present distance to the ridge over the present opening rate would say 4.2 Myr; the state does not. The
        # bound is the angular tolerance of the two longitudes it is computed from, over that rate.
        present_rate = D3['plate_deg_per_Myr'][-1]-D3['ridge_deg_per_Myr'][-1]
        false_age = (midpoint-ridge)/present_rate
        bound = 2*resolved/present_rate
        self.assertLessEqual(abs(false_age-LUNE['distance_over_present_rate_myr']), bound)
        self.assertLessEqual(abs((false_age-actual)-(LUNE['distance_over_present_rate_myr']
                                                     - LUNE['trajectory_mean_age_myr'])), bound)

    def test_source_sink_and_heat_accounts_balance_exactly(self):
        final = self.states[-1]
        material = final.material
        supplied = {name: {k: float(v) for k, v in values.items()} for name, values in material.supplied().items()}
        born = 2*lune(LUNE['born_per_side_total_deg'])
        close(self, supplied['mantle-source']['mass_kg:crust'], F.D3_MASS_PER_AREA*born)
        close(self, supplied['mantle-source']['volume_m3:crust'], F.D3_THICKNESS*born)
        close(self, supplied['mantle-source']['enthalpy_j'], F.D3_ENTHALPY_PER_AREA*born)
        # The trench consumed (east - west) rate times duration of the western plate: 6 + 7.5 degrees.
        self.assertEqual(sum(east-west for east, west in map(stage_rotations, (0, 1))), LUNE['consumed_total_deg'])
        consumed = lune(LUNE['consumed_total_deg'])
        close(self, -supplied['trench|boundary-m04']['area_m2'], consumed)
        close(self, -supplied['slab']['mass_kg:crust'], F.D3_MASS_PER_AREA*consumed)
        close(self, -supplied['slab']['volume_m3:crust'], F.D3_THICKNESS*consumed)
        close(self, -supplied['slab']['enthalpy_j'], F.INHERITED_ENTHALPY_PER_AREA*consumed)   # inherited, cooler
        # Area born equals area consumed on the closed sphere; the faces still cover it once.
        self.assertEqual(2*LUNE['born_per_side_total_deg'], LUNE['consumed_total_deg'])
        for state in self.states:
            self.assertLessEqual(abs(state.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
            self.assertLessEqual(abs(state.material.totals()['area_m2']-SPHERE_M2), AREA_CLOSURE_SR*R*R)
            self.assertTrue(state.material.closure()['identity_exact'])
        # Exact identity, account by account, from the stored record itself: stored pieces = declared + supplied +
        # rounding, the declared totals are the initial state's, and the rounding lies within its allowance.
        record = material.descriptor()['exact']
        declared, rounding, allowance = (exact(material, name) for name in ('initial', 'rounding', 'allowance'))
        for index, column in enumerate(material.columns):
            given = sum((Fraction(values[index]) for values in record['supplied'].values()), Fraction(0))
            self.assertEqual(material.exact_total(column), declared[index]+given+rounding[index])
            self.assertEqual(declared[index], self.states[0].material.exact_total(column))
            self.assertLessEqual(abs(rounding[index]), allowance[index])
            self.assertEqual(given, sum((values[column] for values in material.supplied().values()), Fraction(0)))
        self.assertEqual(sorted(supplied), ['mantle-source', 'ridge|boundary-m00|left', 'ridge|boundary-m00|right',
                                           'slab', 'trench|boundary-m04'])

    def test_untouched_faces_keep_their_exact_bytes(self):
        before, after = self.states[0], self.states[1]
        old = {name: i for i, name in enumerate(before.network.face_ids)}
        new = {name: i for i, name in enumerate(after.network.face_ids)}
        consumed = {after.network.face_ids[row[1]] for row in self.steps[0].map.rows if row[0] >= 0 and row[1] >= 0}
        self.assertEqual(consumed, {f for f in before.network.face_ids if F.sector_of(f) == 4})
        pieces = lambda state, face: state.material.stock[state.material.piece_face == face].tobytes()
        for face_id in before.network.face_ids:
            if face_id not in consumed:
                self.assertEqual(pieces(after, new[face_id]), pieces(before, old[face_id]), face_id)
        # The eastern plate's faces only rode east: every one of them keeps its area within round-off.
        for face_id in before.network.face_ids:
            if F.sector_of(face_id) < 4:
                close(self, float(after.network.face_area_m2[new[face_id]]),
                      float(before.network.face_area_m2[old[face_id]]))

    def test_step_record_describes_what_happened(self):
        summary = self.steps[0].summary()
        self.assertEqual((summary['schema'], summary['mode'], summary['producer']), (T.SCHEMA, T.MODE, T.PRODUCER))
        self.assertEqual(summary['interval'], dict(start_s=0., end_s=D3['stages_Myr'][0]*MYR, start_step=0,
                                                   end_step=1))
        self.assertEqual({b['boundary_id']: b['status'] for b in summary['boundaries']},
                         {'boundary-m00': S.RIDGE, 'boundary-m04': S.TRENCH})
        self.assertEqual([j['junction_id'] for j in summary['junctions']], ['junction:N', 'junction:S'])
        self.assertTrue(all(j['closure_residual'] <= ALGEBRA for j in summary['junctions']))
        self.assertEqual((summary['map']['born_faces'], summary['map']['consumed_faces']),
                         (LUNE['born_faces_per_stage'], LUNE['consumed_faces_per_stage']))
        self.assertEqual([(b['boundary_id'], b['side'], b['source'], b['stock']) for b in summary['births']],
                         [('boundary-m00', 'left', 'mantle-source', False),
                          ('boundary-m00', 'right', 'mantle-source', False)])
        self.assertTrue(summary['closure']['identity_exact'])
        self.assertEqual(json.loads(json.dumps(self.steps[0].record())), self.steps[0].record())
        # The ridge moved at the mean rotation of its plates: the D3 ridge rate over the stage.
        ridge = {b['boundary_id']: b for b in summary['boundaries']}['boundary-m00']['rotation']
        expected = F.spin(D3['ridge_deg_per_Myr'][0]*D3['stages_Myr'][0])
        self.assertLessEqual(F.rotation_angle(Rotation(tuple(ridge)), expected), ANGULAR)


class RotatedCoordinatesTests(unittest.TestCase):
    """Seams and poles: the same staged history about a tilted axis, away from the frame's own poles and seam."""

    @classmethod
    def setUpClass(cls):
        cls.states, cls.steps = staged_lune(F.TILT)
        cls.plain, _ = staged_lune()

    def test_junctions_at_the_tilted_poles_close_within_the_existing_band(self):
        for step in self.steps:
            summary = step.summary()
            self.assertLessEqual(summary['attachment_rad'], BAND)
            for junction in summary['junctions']:
                self.assertLessEqual(junction['spread_rad'], BAND)
                self.assertLessEqual(junction['closure_residual'], ALGEBRA)
        directions = self.states[-1].network.vertex_direction
        self.assertTrue(np.all(np.abs(directions[:, 2]) < 1))                 # no vertex on a frame pole

    def test_accounts_agree_with_the_untilted_history(self):
        tilted, plain = self.states[-1], self.plain[-1]
        self.assertEqual(tilted.network.face_ids, plain.network.face_ids)
        np.testing.assert_allclose(tilted.network.face_area_m2, plain.network.face_area_m2, rtol=RELATIVE, atol=0)
        one, two = tilted.material.supplied(), plain.material.supplied()
        self.assertEqual(sorted(one), sorted(two))
        for name in one:
            for column, value in one[name].items():
                if value:
                    close(self, float(value), float(two[name][column]))
        for side in S.SIDES:
            close(self, float(one['ridge|boundary-m00|'+side]['area_m2']), lune(LUNE['born_per_side_total_deg']))
        self.assertTrue(tilted.material.closure()['identity_exact'])
        self.assertLessEqual(abs(tilted.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
        first = np.concatenate([longitudes(tilted, f, F.TILT) for f in strips(tilted, 'boundary-m00', 'right', 1)])
        low, high = LUNE['stage_1_strip_longitudes_deg']
        self.assertLessEqual(abs(first.min()-low), math.degrees(ANGULAR))
        self.assertLessEqual(abs(first.max()-high), math.degrees(ANGULAR))


class OnePlateTests(unittest.TestCase):
    """One plate rotating between two fixed neighbours: a ridge behind it and a trench ahead of it."""

    def moved(self, degrees=TURN, tilt=None, **changes):
        state = F.crust(F.three_plates(tilt=tilt), **changes)
        return state, T.advance(state, F.one_plate_motion(degrees, tilt=tilt), end_time_s=ONE['interval_myr']*MYR)

    def test_area_mass_volume_and_enthalpy_balance_exactly(self):
        state, step = self.moved()
        after = step.state
        supplied = after.material.supplied()
        value = lambda name, column: float(supplied[name][column])
        # A's trailing edge leaves the ridge by 3 degrees: 1.5 on either side; its leading edge loses 3 degrees.
        half = ONE['expects']['born_per_side_deg']
        self.assertEqual((half, ONE['expects']['consumed_deg']), (TURN/2, TURN))
        close(self, value('ridge|boundary-m02|left', 'area_m2'), lune(half))
        close(self, value('ridge|boundary-m02|right', 'area_m2'), lune(half))
        close(self, -value('trench|boundary-m04', 'area_m2'), lune(TURN))
        close(self, value('mantle-source', 'mass_kg:crust'), F.D3_MASS_PER_AREA*lune(TURN))
        close(self, -value('slab', 'mass_kg:crust'), F.D3_MASS_PER_AREA*lune(TURN))
        close(self, value('mantle-source', 'volume_m3:crust'), F.D3_THICKNESS*lune(TURN))
        close(self, value('mantle-source', 'enthalpy_j'), F.D3_ENTHALPY_PER_AREA*lune(TURN))
        close(self, -value('slab', 'enthalpy_j'), F.INHERITED_ENTHALPY_PER_AREA*lune(TURN))
        # Exact balances: every account's stored total is its declared total plus what was supplied, exactly.
        self.assertTrue(after.material.closure()['identity_exact'])
        for index, column in enumerate(after.material.columns):
            given = sum((values[column] for values in supplied.values()), Fraction(0))
            self.assertEqual(declared_and_supplied(after.material)[index],
                             state.material.exact_total(column)+given)
        close(self, after.material.totals()['area_m2'], state.material.totals()['area_m2'])
        self.assertLessEqual(abs(after.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
        areas = after.network.plate_area_m2()
        close(self, areas['A'], SPHERE_M2/3-lune(half))                 # +1.5 at the ridge, -3 at the trench
        close(self, areas['B'], SPHERE_M2/3)
        close(self, areas['C'], SPHERE_M2/3+lune(half))

    def test_fixed_neighbours_are_untouched_and_the_locked_boundary_does_not_move(self):
        state, step = self.moved()
        after = step.state
        old = {name: i for i, name in enumerate(state.network.face_ids)}
        new = {name: i for i, name in enumerate(after.network.face_ids)}
        lookup = lambda s: {name: i for i, name in enumerate(s.network.vertex_ids)}
        before, later = lookup(state), lookup(after)
        where = lambda s, table, ring: s.network.vertex_direction[[table[name] for name in ring]].tobytes()
        for face_id in state.network.face_ids:
            if state.network.face_plate(face_id) in ('B', 'C'):
                # The same face at the same place with the same material; beside the ridge its corners are now
                # the plate's own copies of the old ridge vertices, which did not move with fixed C.
                self.assertEqual(where(after, later, after.network.face(face_id).vertex_ids),
                                 where(state, before, state.network.face(face_id).vertex_ids), face_id)
                self.assertEqual(after.material.stock[after.material.piece_face == new[face_id]].tobytes(),
                                 state.material.stock[state.material.piece_face == old[face_id]].tobytes())
                if F.sector_of(face_id) != 1:                          # not beside the ridge: the same record
                    self.assertEqual(after.network.face(face_id), state.network.face(face_id))
        for name in F.chain(0, 5)+F.chain(4, 5):                       # B|C is locked; the trench rides fixed B
            self.assertEqual(after.network.vertex_direction[later[name]].tobytes(),
                             state.network.vertex_direction[before[name]].tobytes())
        status = {b['boundary_id']: b['status'] for b in step.summary()['boundaries']}
        self.assertEqual(status, {'boundary-m00': T.LOCKED, 'boundary-m02': S.RIDGE, 'boundary-m04': S.TRENCH})
        self.assertLessEqual(F.rotation_angle(after.network.plate('A').rotation, F.spin(TURN)), ANGULAR)
        self.assertEqual(after.network.plate('B').rotation.quaternion, (1., 0., 0., 0.))
        # One shared record per interface, as before; only the faces beside the ridge are new.
        self.assertEqual([b.boundary_id for b in after.network.boundaries],
                         [b.boundary_id for b in state.network.boundaries])
        self.assertEqual(len(after.network.face_ids), len(state.network.face_ids)+ONE['expects']['born_faces'])
        self.assertEqual(step.summary()['map']['consumed_faces'], ONE['expects']['consumed_faces'])
        self.assertEqual({after.network.face_plate(f) for f in strips(after, 'boundary-m02', 'left', 1)}, {'C'})
        self.assertEqual({after.network.face_plate(f) for f in strips(after, 'boundary-m02', 'right', 1)}, {'A'})

    def test_the_same_motion_in_rotated_coordinates_gives_the_same_accounts(self):
        _, plain = self.moved()
        _, tilted = self.moved(tilt=F.TILT)
        one, two = tilted.state.material.supplied(), plain.state.material.supplied()
        for name in two:
            for column, value in two[name].items():
                if value:
                    close(self, float(one[name][column]), float(value))
        np.testing.assert_allclose(tilted.state.network.face_area_m2, plain.state.network.face_area_m2,
                                   rtol=RELATIVE, atol=0)
        self.assertTrue(tilted.state.material.closure()['identity_exact'])

    def test_destinations_are_partitioned_exactly_as_declared(self):
        (first, share), (second, rest) = ONE['destinations']
        state = F.crust(F.three_plates(), exteriors=F.EXTERIORS+((second, 'sink'),))
        motion = F.one_plate_motion(TURN, sinks=(F.sink('boundary-m04', ((first, share), (second, rest))),))
        after = T.advance(state, motion, end_time_s=MYR).state
        supplied = after.material.supplied()
        for column in ('mass_kg:crust', 'volume_m3:crust', 'enthalpy_j'):
            self.assertEqual(supplied[first][column]*Fraction(rest),
                             supplied[second][column]*Fraction(share))               # exact rationals
            self.assertNotEqual(supplied[second][column], 0)
        self.assertNotIn('area_m2', {k for k, v in supplied[first].items() if v})
        self.assertTrue(after.material.closure()['identity_exact'])
        with self.assertRaises(L.LedgerError):
            F.sink('boundary-m04', ((first, share), (second, rest/2)))                 # does not sum to one
        with self.assertRaises(L.LedgerError):
            F.sink('boundary-m04', ((first, .5), (first, .5)))
        with self.assertRaises(TectonicsError):
            F.sink('boundary-m04', ((first, 1.), (second, 0.)))

    def test_consumption_carries_every_cohort_of_the_cell_and_never_resets_an_age(self):
        start, end = (value*MYR for value in ONE['inherited_formed_myr'])
        dated = (F.cohort('inherited-A', start=start, end=end), F.cohort('inherited-B'), F.cohort('inherited-C'))
        state, step = self.moved(cohorts=dated)
        after = step.state
        now = ONE['interval_myr']*MYR
        self.assertEqual(after.material.cohort('inherited-A'), state.material.cohort('inherited-A'))
        self.assertEqual(after.material.ages_s(now)['inherited-A'], (now-end, now-start))
        # The trench cells of A still hold only their inherited cohort; the remainder is what was not consumed.
        cells = [f for f in state.network.face_ids if F.sector_of(f) == 3]
        for face_id in cells:
            self.assertEqual(after.material.face_cohorts(face_id), ('inherited-A',))
        old = {name: i for i, name in enumerate(state.network.face_ids)}
        new = {name: i for i, name in enumerate(after.network.face_ids)}
        kept = math.fsum(float(after.network.face_area_m2[new[f]]) for f in cells)
        close(self, kept, math.fsum(float(state.network.face_area_m2[old[f]]) for f in cells)-lune(TURN))


class DeclaredRuleTests(unittest.TestCase):
    """The declared accretion fraction and boundaries oblique to the motion."""

    def test_a_declared_accretion_fraction_divides_the_opening_between_the_two_sides(self):
        control = F.control('asymmetric_ridge')
        turn, end = control['rotation_deg'], control['interval_myr']*MYR
        ridge = 'boundary-'+F.meridian(control['ridge_meridian'])
        for fraction in control['accretion_fractions']:
            with self.subTest(fraction=fraction):
                state = F.crust(F.three_plates(kinds={control['ridge_meridian']: dict(
                    kind=S.RIDGE, accretion_fraction=fraction)}))
                shares = {'left': fraction, 'right': 1-fraction}
                supplies = tuple(F.supply(ridge, side) for side in S.SIDES if shares[side] > 0)
                step = T.advance(state, F.one_plate_motion(turn, supplies=supplies), end_time_s=end)
                supplied = step.state.material.supplied()
                for side in S.SIDES:
                    party = 'ridge|%s|%s' % (ridge, side)
                    if shares[side] > 0:
                        close(self, float(supplied[party]['area_m2']), lune(shares[side]*turn))
                    else:
                        self.assertNotIn(party, supplied)                   # that side opens nothing
                close(self, -float(supplied['trench|boundary-m04']['area_m2']), lune(turn))
                self.assertTrue(step.state.material.closure()['identity_exact'])
                # The ridge moved by the blend of its plates' rotations: (1-f) of fixed C and f of A.
                moved = {b['boundary_id']: b for b in step.summary()['boundaries']}[ridge]
                self.assertLessEqual(F.rotation_angle(Rotation(tuple(moved['rotation'])), F.spin(fraction*turn)),
                                     ANGULAR)
                if min(shares.values()) == 0:
                    # A supply declared for the side that opens nothing is refused, not ignored.
                    with self.assertRaises(T.TransferRefused) as caught:
                        T.advance(state, F.one_plate_motion(turn), end_time_s=end)
                    self.assertIn('opens nothing', str(caught.exception))

    def test_boundaries_oblique_to_the_motion_balance_like_straight_ones(self):
        control = F.control('oblique_boundaries')
        turn, end = control['rotation_deg'], control['interval_myr']*MYR
        for tilt in (None, F.TILT):
            with self.subTest(tilted=tilt is not None):
                state = F.crust(F.three_plates(tilt=tilt, zigzag_deg=control['zigzag_deg']))
                step = T.advance(state, F.one_plate_motion(turn, tilt=tilt), end_time_s=end)
                after = step.state
                supplied = after.material.supplied()
                for side in S.SIDES:
                    close(self, float(supplied['ridge|boundary-m02|'+side]['area_m2']), lune(turn/2))
                close(self, -float(supplied['trench|boundary-m04']['area_m2']), lune(turn))
                close(self, -float(supplied['slab']['mass_kg:crust']), F.D3_MASS_PER_AREA*lune(turn))
                self.assertTrue(after.material.closure()['identity_exact'])
                self.assertLessEqual(abs(after.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
                areas = after.network.plate_area_m2()
                close(self, areas['A'], SPHERE_M2/3-lune(turn/2))
                close(self, areas['B'], SPHERE_M2/3)
                close(self, areas['C'], SPHERE_M2/3+lune(turn/2))


class SlowBoundaryTests(unittest.TestCase):
    """Motions far smaller than a cell are measured at the resolution of the cells, never refused as exhaustion."""

    control = F.control('slow_boundary')

    def test_slow_ridge_and_trench_balance_at_the_resolution_of_their_cells(self):
        # 1e-4 degrees is 11 m of plate motion and 1e-10 degrees 11 micrometres: both far above the attachment
        # band. An overlap is measured to the existing relative tolerance of the cells it is cut from (here one
        # 60 degree sector), not of the thin strip itself, so that is the declared resolution of both accounts.
        resolution = RELATIVE*SPHERE_M2/6
        for tilt in (None, F.TILT):
            for degrees in self.control['rotation_deg']:
                with self.subTest(tilted=tilt is not None, degrees=degrees):
                    self.assertGreater(math.radians(degrees), BAND)
                    state = F.crust(F.three_plates(tilt=tilt))
                    step = T.advance(state, F.one_plate_motion(degrees, tilt=tilt),
                                     end_time_s=self.control['interval_myr']*MYR)
                    supplied = step.state.material.supplied()
                    born = sum(float(supplied['ridge|boundary-m02|'+side]['area_m2']) for side in S.SIDES)
                    consumed = -float(supplied['trench|boundary-m04']['area_m2'])
                    self.assertGreater(consumed, 0.)
                    self.assertLessEqual(abs(consumed-lune(degrees)), resolution)
                    self.assertLessEqual(abs(born-lune(degrees)), resolution)
                    self.assertTrue(step.state.material.closure()['identity_exact'])
                    self.assertEqual((step.summary()['map']['born_faces'], step.summary()['map']['consumed_faces']),
                                     (ONE['expects']['born_faces'], ONE['expects']['consumed_faces']))

    def test_strips_born_slowly_ride_on_through_later_intervals(self):
        # A strip a few metres wide is measured once, when it is born. Afterwards it only rides with its plate:
        # its vertices are rounded again and its ring may start elsewhere, which changes its measured area by far
        # more than the relative tolerance although nothing happened to it. It must not be measured against its
        # pieces again.
        follow, end = self.control['followed_by_deg'], self.control['interval_myr']*MYR
        turn = F.rotation(F.control('rigid_rotation')['rotation'])
        for tilt in (None, F.TILT):
            for degrees in self.control['rotation_deg']:
                with self.subTest(tilted=tilt is not None, degrees=degrees):
                    state = F.crust(F.three_plates(tilt=tilt))
                    first = T.advance(state, F.one_plate_motion(degrees, tilt=tilt), end_time_s=end).state
                    second = T.advance(first, F.one_plate_motion(follow, step=1, tilt=tilt), end_time_s=2*end).state
                    born = [f for f in first.network.face_ids if f.startswith('boundary-m02|')]
                    self.assertEqual(len(born), ONE['expects']['born_faces'])
                    old = {name: i for i, name in enumerate(first.network.face_ids)}
                    new = {name: i for i, name in enumerate(second.network.face_ids)}
                    for face_id in born:
                        self.assertEqual(
                            second.material.stock[second.material.piece_face == new[face_id]].tobytes(),
                            first.material.stock[first.material.piece_face == old[face_id]].tobytes(), face_id)
                    self.assertTrue(second.material.closure()['identity_exact'])
                    third = T.advance(second, T.Motion(2, 3, {plate: turn for plate in 'ABC'}), end_time_s=3*end)
                    self.assertEqual(third.map.rows, ())
                    self.assertEqual(third.state.material.stock.tobytes(), second.material.stock.tobytes())
        # Several slow intervals in a row: the accounts follow the summed lune.
        steady = self.control['consecutive']
        state = F.crust(F.three_plates())
        for k in range(steady['intervals']):
            state = T.advance(state, F.one_plate_motion(steady['rotation_deg'], step=k), end_time_s=(k+1)*end).state
        supplied = state.material.supplied()
        total = lune(steady['rotation_deg']*steady['intervals'])
        self.assertLessEqual(abs(-float(supplied['trench|boundary-m04']['area_m2'])-total), RELATIVE*SPHERE_M2/6)
        self.assertTrue(state.material.closure()['identity_exact'])
        restored = S.restore_sphere(state.descriptor(), state.arrays())
        self.assertEqual(restored.state_id, state.state_id)

    def test_relative_motion_inside_the_attachment_band_moves_no_material(self):
        # 1e-13 degrees is 1.7e-15 rad: the plates' own positions of every boundary vertex coincide within the
        # existing 64 eps band, so nothing opens and nothing is consumed; the step records the attachment.
        degrees, end = self.control['inside_band_deg'], self.control['interval_myr']*MYR
        self.assertLess(math.radians(degrees), BAND)
        state = F.crust(F.three_plates())
        step = T.advance(state, F.one_plate_motion(degrees, supplies=(), sinks=()), end_time_s=end)
        self.assertEqual(step.map.rows, ())
        self.assertEqual(step.state.material.stock.tobytes(), state.material.stock.tobytes())
        self.assertEqual(step.state.network.face_ids, state.network.face_ids)
        self.assertTrue(0. < step.summary()['attachment_rad'] <= BAND)
        # A supply or destination declared for it is refused: there is nothing for it to supply or receive.
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, F.one_plate_motion(degrees), end_time_s=end)
        self.assertIn('nothing in this interval', str(caught.exception))


class SmallFaceTests(unittest.TestCase):
    """Cells of very different sizes, and cells too large to share a chart with what they cannot overlap."""

    def test_tiny_polar_faces_beside_large_cells_balance(self):
        # Polar triangles about 1 km and 11 m tall are below what the relative tolerance can certify (see the
        # case's resolution_note): a step is accepted with the right balances or refused as unresolved, never
        # accepted wrongly and never refused for another reason.
        control = F.control('polar_rows')
        end, resolution = control['interval_myr']*MYR, RELATIVE*SPHERE_M2/6
        accepted = refused = 0
        for top in control['top_latitude_deg']:
            rows = (-top, -60., 0., 60., top)
            for tilt in (None, F.TILT):
                for degrees in control['rotation_deg']:
                    with self.subTest(top=top, tilted=tilt is not None, degrees=degrees):
                        state = F.crust(F.three_plates(latitudes_deg=rows, tilt=tilt))
                        try:
                            step = T.advance(state, F.one_plate_motion(degrees, tilt=tilt), end_time_s=end)
                        except T.TransferRefused as refusal:
                            self.assertEqual(refusal.code, T.UNRESOLVED_OVERLAP, refusal)
                            refused += 1
                            continue
                        accepted += 1
                        supplied = step.state.material.supplied()
                        born = sum(float(supplied['ridge|boundary-m02|'+side]['area_m2']) for side in S.SIDES)
                        consumed = -float(supplied['trench|boundary-m04']['area_m2'])
                        self.assertLessEqual(abs(born-lune(degrees)), resolution)
                        self.assertLessEqual(abs(consumed-lune(degrees)), resolution)
                        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertGreater(accepted, 0)

    def test_a_small_overlap_far_from_the_chart_centre_is_measured_at_its_own_scale(self):
        # A square 1.3 m across inside a cell thousands of kilometres across, far from the cell's centre. Its
        # overlap with the cell is the square itself, whose area is known exactly; the existing W01 tolerance for
        # small spherical areas applies. Measuring it from an anchor at the chart's centre misses by far more.
        control = F.control('polar_rows')['small_overlap']
        small = json.loads((F.CASES/'w01_geometry.json').read_text(encoding='utf-8'))['acceptance'][
            'small_spherical_area_relative']
        half = control['half_width_rad']
        expected = 4*math.atan(half*half/math.sqrt(1+2*half*half))
        for tilt in (None, F.TILT):
            network = F.three_plates(tilt=tilt)
            lookup = {name: index for index, name in enumerate(network.vertex_ids)}
            ring = network.vertex_direction[[lookup[name] for name in network.face(control['face']).vertex_ids]]
            corner = F.longitude_deg(ring[:1], tilt)[0]+control['offset_deg'][0], -30.+control['offset_deg'][1]
            centre = np.array(F.direction(*corner))
            if tilt is not None:
                centre = tilt.apply(centre)
            east = np.cross(centre, (0.3, 0.5, 0.8))
            east /= np.linalg.norm(east)
            north = np.cross(centre, east)
            square = np.array([centre+half*(x*east+y*north) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
            square /= np.linalg.norm(square, axis=1)[:, None]
            measured = T._overlap_sr([ring], [square], network.sphere)
            self.assertLessEqual(abs(measured-expected), small*expected, (measured, expected))
            self.assertEqual(T._overlap_sr([square], [ring], network.sphere), measured)

    def test_the_orientation_of_a_tiny_ring_is_decided_at_its_own_scale(self):
        # A triangle a few metres across, anywhere on the sphere: its orientation is the sign of a determinant that
        # must be formed from differences of its own corners, not from three nearly equal unit vectors.
        rng = np.random.default_rng(20261002)
        for size in (1e-3, 1e-6, 1e-9, 1e-12):
            for _ in range(25):
                centre = rng.normal(size=3)
                centre /= np.linalg.norm(centre)
                east = np.cross(centre, rng.normal(size=3))
                east /= np.linalg.norm(east)
                north = np.cross(centre, east)
                ring = [centre+size*(math.cos(a)*east+math.sin(a)*north) for a in (0.3, 2.1, 4.4)]
                ring = np.array([p/np.linalg.norm(p) for p in ring])
                self.assertTrue(T._turns_left(ring), size)
                self.assertFalse(T._turns_left(ring[::-1]), size)

    def test_faces_that_a_great_circle_separates_need_no_shared_chart(self):
        control = F.control('coarse_rows')
        turn, end = control['rotation_deg'], control['interval_myr']*MYR
        for tilt in (None, F.TILT):
            with self.subTest(tilted=tilt is not None):
                state = F.crust(F.three_plates(latitudes_deg=tuple(control['latitudes_deg']), tilt=tilt))
                step = T.advance(state, F.one_plate_motion(turn, tilt=tilt), end_time_s=end)
                supplied = step.state.material.supplied()
                for side in S.SIDES:
                    close(self, float(supplied['ridge|boundary-m02|'+side]['area_m2']), lune(turn/2))
                close(self, -float(supplied['trench|boundary-m04']['area_m2']), lune(turn))
                self.assertTrue(step.state.material.closure()['identity_exact'])
        # Two faces that do overlap but fit no common chart are still refused, never split silently.
        wide = F.sector_world((0., 120., 240.), (-30., 0., 30.), plates=('C', 'A', 'B'),
                              kinds={0: dict(kind=S.TRANSFORM), 1: dict(kind=S.RIDGE, accretion_fraction=.5),
                                     2: dict(kind=S.TRENCH, subducting_side='left')})
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(F.crust(wide), F.one_plate_motion(turn, ridge='boundary-m01', trench='boundary-m02'),
                      end_time_s=end)
        self.assertEqual(caught.exception.code, T.UNRESOLVED_OVERLAP)


class ExactConsumptionTests(unittest.TestCase):
    """M3 accuracy and refusal controls: analytical signed supports, plus the original swept-relative audit."""

    def test_exact_clipping_preserves_concavity_holes_and_small_intersections(self):
        from test_i03_thin_faces import true_area
        sphere = F.three_plates().sphere

        def ring(points):
            values = np.asarray([(x, y, 1.) for x, y in points])
            return values/np.linalg.norm(values, axis=1)[:, None]

        outer = ring(((-.4, -.4), (.4, -.4), (.4, .4), (-.4, .4)))
        hole = ring(((-.1, -.1), (.1, -.1), (.1, .1), (-.1, .1)))
        right = ring(((0., -.5), (.5, -.5), (.5, .5), (0., .5)))
        half = ring(((0., -.4), (.4, -.4), (.4, .4), (0., .4)))
        half_hole = ring(((0., -.1), (.1, -.1), (.1, .1), (0., .1)))
        # Both sides have holes: inclusion-exclusion restores their shared hole instead of subtracting it twice.
        for first, second, expected in (
                ([outer, hole], [outer, hole], float(true_area([outer, hole]))),
                ([outer, hole], [right], float(true_area([half, half_hole])))):
            close(self, T._exact_overlap_sr(first, second, sphere), expected)
            close(self, T._exact_overlap_sr(second, first, sphere), expected)
        concave = ring(((-.4, -.4), (.4, -.4), (.4, 0.), (0., 0.), (0., .4), (-.4, .4)))
        close(self, T._exact_overlap_sr([concave], [outer], sphere), float(true_area([concave])))
        width = 2.**-24
        tiny = ring(((-width, -width), (width, -width), (width, width), (-width, width)))
        analytic = 4*math.atan(width*width/math.sqrt(1+2*width*width))
        close(self, T._exact_overlap_sr([outer], [tiny], sphere), analytic)
        with self.assertRaises(MemoryLimitError):
            T._exact_overlap_sr([outer], [tiny], sphere, budget=WorkBudget(1024))

    def test_a_trench_is_held_to_its_sweep_not_its_large_donor_cells(self):
        state = F.crust(F.three_plates(tilt=F.TILT))
        motion = F.one_plate_motion(F.control('clock_commit')['slow_then_normal_deg'][0], tilt=F.TILT)
        step = T.advance(state, motion, end_time_s=MYR)
        rows = step.map._motion
        k = next(i for i, target in enumerate(rows.receiver) if target < 0)
        sweep = step.summary()['consumption_accuracy']['boundary-m04']['swept_area_m2']
        values = list(rows.area_m2)
        values[k] += 2*RELATIVE*sweep
        forged = replace(rows, area_m2=tuple(values))
        network = step.state.network
        mapped = T._map(state.network, network, network, motion, forged, None)
        with self.assertRaisesRegex(T.TransferRefused, 'sweeps'):
            T.advance(state, motion, end_time_s=MYR, prepared=mapped)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.state = F.crust(F.three_plates())

    def refused(self, text, state=None, end_time_s=MYR, **changes):
        state = self.state if state is None else state
        values = dict(start_step=0, end_step=1, rotations={'A': F.spin(TURN), 'B': F.IDENTITY, 'C': F.IDENTITY},
                      supplies=F.both_sides('boundary-m02'), sinks=(F.sink('boundary-m04'),))
        values.update(changes)
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, T.Motion(**values), end_time_s=end_time_s)
        self.assertIn(text, str(caught.exception))
        self.assertIsInstance(caught.exception, L.ExchangeRefused)

    def test_every_plate_needs_its_rotation(self):
        self.refused('absent motion is unknown', rotations={'A': F.spin(TURN), 'B': F.IDENTITY})
        self.refused('absent motion is unknown', rotations={'A': F.spin(TURN), 'B': F.IDENTITY, 'C': F.IDENTITY,
                                                            'D': F.IDENTITY})

    def test_interval_must_continue_the_parent(self):
        self.refused('cannot be applied to the state at step 0', start_step=1, end_step=2)
        self.refused('must end after', end_time_s=0.)
        with self.assertRaises(L.LedgerError):
            T.Motion(2, 2, {'A': F.IDENTITY})
        with self.assertRaises(L.LedgerError):
            T.Motion(0, I.MAX_STEPS+1, {'A': F.IDENTITY})

    def test_negative_half_rate_is_refused(self):
        self.refused('negative half-rate', rotations={'A': F.spin(REFUSALS['closing_ridge_deg']), 'B': F.IDENTITY,
                                                      'C': F.IDENTITY})

    def test_negative_consumption_is_refused(self):
        # B, the overriding plate, backs away from A: the trench would open. C subducts beneath B instead.
        retreat = REFUSALS['retreating_override']
        state = F.crust(F.three_plates(kinds={retreat['trench_meridian']: dict(
            kind=S.TRENCH, subducting_side=retreat['subducting_side'])}))
        self.refused('consumption must be positive', state=state,
                     rotations={'A': F.IDENTITY, retreat['plate']: F.spin(retreat['rotation_deg']),
                                'C': F.IDENTITY}, supplies=(),
                     sinks=(F.sink('boundary-m00'), F.sink('boundary-m04')))

    def test_sliding_transform_is_refused(self):
        sliding = REFUSALS['sliding_transform']
        turn = F.spin(sliding['rotation_deg'])
        state = F.crust(F.octahedron(), cohort_of=lambda face: 'inherited', exteriors=())
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, T.Motion(0, 1, {'north': turn, 'south': F.IDENTITY}), end_time_s=MYR)
        self.assertIn('sliding along a transform', str(caught.exception))
        together = T.advance(state, T.Motion(0, 1, {'north': turn, 'south': turn}), end_time_s=MYR)
        self.assertEqual(together.map.rows, ())

    def test_junction_that_its_records_would_move_apart_is_refused(self):
        # About another axis the pole junctions are carried apart by the ridge, the trench and the fixed plates:
        # they would have to migrate along their boundaries or reorganise, and this version does neither.
        tipped = REFUSALS['tipped']
        turn = Rotation.from_axis_angle(tuple(tipped['axis']), math.radians(tipped['angle_deg']))
        self.refused('move it to different points', rotations={'A': turn, 'B': F.IDENTITY, 'C': F.IDENTITY})

    def test_exhausted_boundary_cell_is_refused_not_clipped(self):
        # A's trench cells are 60 degrees wide; 70 degrees of consumption would need more than they hold.
        self.assertGreater(REFUSALS['exhausting_deg'], REFUSALS['cell_width_deg'])
        self.assertLess(REFUSALS['sufficient_deg'], REFUSALS['cell_width_deg'])
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(self.state, F.one_plate_motion(REFUSALS['exhausting_deg']), end_time_s=MYR)
        self.assertIn('exhausted', str(caught.exception))
        # Up to the cell's width the stock is finite but sufficient.
        almost = T.advance(self.state, F.one_plate_motion(REFUSALS['sufficient_deg']), end_time_s=MYR).state
        close(self, -float(almost.material.supplied()['trench|boundary-m04']['area_m2']),
              lune(REFUSALS['sufficient_deg']))

    def test_supplies_and_destinations_are_declared_never_assumed(self):
        self.refused('no supply is declared', supplies=(F.supply('boundary-m02', 'left'),))
        self.refused('no destination is declared', sinks=())
        self.refused('not a ridge', supplies=F.both_sides('boundary-m02')+(F.supply('boundary-m04', 'left'),))
        self.refused('not a trench', sinks=(F.sink('boundary-m04'), F.sink('boundary-m02')))
        self.refused('not a declared exterior source', supplies=F.both_sides('boundary-m02', source='slab'))
        self.refused('not a declared exterior sink',
                     sinks=(F.sink('boundary-m04', (('mantle-source', 1.),)),))
        self.refused('no stock link', supplies=F.both_sides('boundary-m02', stock=True))
        self.refused('no stock link', sinks=(F.sink('boundary-m04', (('slab', 1., True),)),))

    def test_supply_must_match_the_carried_accounts(self):
        self.refused('other phases', supplies=F.both_sides(
            'boundary-m02', mass_per_area_kg_m2={'basalt': 1.}, thickness_m={'basalt': 1.}))
        self.refused('signed enthalpy exactly when', supplies=F.both_sides('boundary-m02',
                                                                          enthalpy_per_area_j_m2=None))
        bare = F.crust(F.three_plates(), basis=None, enthalpy_per_area_j_m2=None)
        self.refused('signed enthalpy exactly when', state=bare)
        cold = T.advance(bare, F.one_plate_motion(
            TURN, supplies=F.both_sides('boundary-m02', enthalpy_per_area_j_m2=None)), end_time_s=MYR).state
        self.assertNotIn('enthalpy_j', cold.material.columns)                  # still unknown, not zero
        self.assertEqual({e['name'] for e in cold.unknown()}, {'sphere.enthalpy_j'})

    def test_malformed_proposals_are_refused(self):
        for bad in (lambda: T.Motion(0, 1, {'A': 'spin'}), lambda: T.Motion(0, 1, {}),
                    lambda: T.Motion(0, 1, {'A': F.IDENTITY}, supplies=('ridge',)),
                    lambda: F.supply('boundary-m02', 'middle'),
                    lambda: F.supply('boundary-m02', 'left', mass_per_area_kg_m2={'crust': -1.}),
                    lambda: T.Motion(0, 1, {'A': F.IDENTITY}, supplies=F.both_sides('b')+F.both_sides('b')),
                    lambda: T.Sink('boundary-m04', ()), lambda: T.Motion(True, 1, {'A': F.IDENTITY})):
            with self.assertRaises(TectonicsError):
                bad()
        with self.assertRaises(T.TransferRefused):
            T.advance(self.state, 'motion', end_time_s=MYR)
        with self.assertRaises(T.TransferRefused):
            T.advance(self.state.network, still(self.state.network), end_time_s=MYR)

    def test_accounts_that_cannot_be_stored_exactly_refuse_the_step(self):
        # Six exact binary fractions with long tails, applied to a denormal areal mass, need more digits than a
        # stored exact account may have. The step must refuse, not issue a state its own restoration refuses.
        names = ['d%d' % index for index in range(6)]
        fractions = [1-2.**-53]+[2.**(-53*i)-2.**(-53*(i+1)) for i in range(1, 5)]+[2.**-265]
        self.assertEqual(sum(map(Fraction, fractions)), 1)
        sink = F.sink('boundary-m04', tuple(zip(names, fractions)))
        tiny = F.crust(F.three_plates(), exteriors=F.EXTERIORS+tuple((name, 'sink') for name in names),
                       mass_per_area_kg_m2={'crust': 1e-323})
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(tiny, F.one_plate_motion(TURN, sinks=(sink,)), end_time_s=MYR)
        self.assertIn('bounded exact representation', str(caught.exception))
        usual = F.crust(F.three_plates(), exteriors=F.EXTERIORS+tuple((name, 'sink') for name in names))
        after = T.advance(usual, F.one_plate_motion(TURN, sinks=(sink,)), end_time_s=MYR).state
        self.assertEqual(S.restore_sphere(after.descriptor(), after.arrays()).state_id, after.state_id)

    def test_refusal_leaves_the_parent_usable(self):
        self.refused('negative half-rate', rotations={'A': F.spin(REFUSALS['closing_ridge_deg']), 'B': F.IDENTITY,
                                                      'C': F.IDENTITY})
        again = T.advance(self.state, F.one_plate_motion(TURN), end_time_s=MYR)
        self.assertEqual(again.parent_state_id, self.state.state_id)


class MeshChangeTests(unittest.TestCase):
    """A mesh change without motion: the same plates and interfaces on other sampling faces."""

    def test_a_rename_preserves_an_event_allowance_above_the_thin_face_range(self):
        # D7-prime's exact rename carries A unchanged, including the distinct D7-double-prime allowance an event
        # left above C7's range. A legal declaration just inside rho exposes a reset even after one event.
        from atlas_tectonics import integration_events as E
        rule = json.loads((F.CASES/'i03_controls_v3.json').read_text())['controls']['reexpression_above_range']

        def merged(initial):
            first = T.advance(initial, F.one_plate_motion(rule['slow_turn_deg']), end_time_s=MYR).state
            return T.advance(first, still(first.network, 1, 2,
                             events=(E.Merge('merge-ac', ('A', 'C'), 'AC', 2*MYR),)), end_time_s=2*MYR).state

        initial = F.crust(F.three_plates())
        observed = merged(initial)
        # This inherited face rides during spreading and its measure changes only when its frame is re-expressed.
        name = 's02-south'
        before = float(initial.network.face_area_m2[initial.network.face_ids.index(name)])
        after = float(observed.network.face_area_m2[observed.network.face_ids.index(name)])
        self.assertNotEqual(before, after)
        sign = 1 if before > after else -1
        fraction = json.loads((F.CASES/'i03_controls_v4.json').read_text())['controls']['rename_allowance']['relative_perturbation_fraction']
        pieces = tuple(replace(p, area_m2=p.area_m2*(1+sign*fraction*RELATIVE)) if p.face_id == name else p
                       for p in initial.material.pieces())
        m = initial.material
        material = S.build_material(initial.network, phases=m.phases, cohorts=m.cohorts, pieces=pieces,
                                    enthalpy_basis=m.enthalpy_basis, exteriors=m.exteriors, stock_link=m.stock_link)
        state = merged(S.initial_sphere(initial.network, material))
        k = state.network.face_ids.index(name)
        held = math.fsum(state.material.stock[state.material.piece_face == k, 0])
        area = float(state.network.face_area_m2[k])
        self.assertGreater(abs(held-area), RELATIVE*area)
        allowance = float(state.material.occupancy_allowance_m2[k])
        self.assertLessEqual(abs(held-area), allowance)
        faces = tuple(replace(face, face_id='renamed') if face.face_id == name else face for face in state.network.faces)
        result = T.advance(state, still(state.network, 2, 3, mesh=T.Mesh(faces)), end_time_s=3*MYR).state
        j = result.network.face_ids.index('renamed')
        self.assertEqual(float(result.material.occupancy_allowance_m2[j]), allowance)
        np.testing.assert_array_equal(result.material.stock[result.material.piece_face == j],
                                      state.material.stock[state.material.piece_face == k])
        self.assertTrue(S.verified(result).material.closure()['identity_exact'])

    control = F.control('mesh_change')

    def setUp(self):
        self.formed = tuple(value*MYR for value in self.control['inherited_east_formed_myr'])
        self.end = self.control['interval_myr']*MYR
        dated = (F.cohort('inherited-east', start=self.formed[0], end=self.formed[1]), F.cohort('inherited-west'))
        self.state = F.crust(F.lune_world(), cohorts=dated)
        self.ages = (self.end-self.formed[1], self.end-self.formed[0])

    def remeshed(self, replace, state=None, **changes):
        state = self.state if state is None else state
        faces = {face.face_id: face for face in state.network.faces}
        for name in replace.get('remove', ()):
            del faces[name]
        for face in replace.get('add', ()):
            faces[face.face_id] = face
        mesh = T.Mesh(tuple(faces.values()), replace.get('vertices', ()))
        return T.advance(state, still(state.network, mesh=mesh, **changes), end_time_s=self.end)

    def test_merging_two_faces_conserves_every_account_exactly(self):
        first, second = self.control['merge']
        merged = S.Face('s01-merged', 'east', (F.vertex(1, 1), F.vertex(2, 1), F.vertex(2, 2), F.vertex(2, 3),
                                               F.vertex(1, 3), F.vertex(1, 2)))
        step = self.remeshed(dict(remove=(first, second), add=(merged,)))
        before, after = self.state, step.state
        self.assertEqual(len(after.network.face_ids), len(before.network.face_ids)-1)
        self.assertEqual(step.map.rows, ())                               # no motion rows
        old = {name: i for i, name in enumerate(before.network.face_ids)}
        new = {name: i for i, name in enumerate(after.network.face_ids)}
        self.assertEqual(sorted((d, r) for d, r, _ in step.map.mesh_rows),
                         [(old[first], new['s01-merged']), (old[second], new['s01-merged'])])
        self.assertEqual(declared_and_supplied(after.material),
                         [before.material.exact_total(column) for column in before.material.columns])
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertEqual(after.material.supplied(), {})                    # nothing came from or went to an exterior
        # The merged face holds the same cohort; its formation dates were not reset.
        self.assertEqual(after.material.face_cohorts('s01-merged'), ('inherited-east',))
        self.assertEqual(after.material.cohorts, before.material.cohorts)
        self.assertEqual(after.material.ages_s(self.end)['inherited-east'], self.ages)
        piece = lambda state, face: state.material.stock[state.material.piece_face == face]
        # Each account of the merged piece is the exact sum of the two, rounded once: the binary64 sum itself.
        np.testing.assert_array_equal(piece(after, new['s01-merged']),
                                      piece(before, old[first])+piece(before, old[second]))
        # Every other face and piece kept its exact bytes, and the physical network did not change.
        for face_id in before.network.face_ids:
            if face_id not in (first, second):
                self.assertEqual(piece(after, new[face_id]).tobytes(), piece(before, old[face_id]).tobytes())
        self.assertEqual(after.network.boundaries, before.network.boundaries)
        self.assertEqual(after.network.plates, before.network.plates)
        self.assertEqual((after.time_s, after.step), (self.end, 1))

    def test_splitting_a_face_divides_its_accounts_by_measured_area(self):
        whole_id = self.control['split']
        halves = (S.Face(whole_id+'-a', 'east', (F.vertex(1, 1), F.vertex(2, 1), F.vertex(2, 2))),
                  S.Face(whole_id+'-b', 'east', (F.vertex(1, 1), F.vertex(2, 2), F.vertex(1, 2))))
        step = self.remeshed(dict(remove=(whole_id,), add=halves))
        before, after = self.state, step.state
        old = {name: i for i, name in enumerate(before.network.face_ids)}
        new = {name: i for i, name in enumerate(after.network.face_ids)}
        whole = before.material.stock[before.material.piece_face == old[whole_id]][0]
        names = [face.face_id for face in halves]
        parts = [after.material.stock[after.material.piece_face == new[name]][0] for name in names]
        areas = [float(after.network.face_area_m2[new[name]]) for name in names]
        close(self, math.fsum(areas), float(before.network.face_area_m2[old[whole_id]]))
        for part, area in zip(parts, areas):
            np.testing.assert_allclose(part, whole*area/math.fsum(areas), rtol=RELATIVE, atol=0)
        # Debited once and completely: every account's exact total is unchanged apart from the booked rounding.
        self.assertEqual(declared_and_supplied(after.material),
                         [before.material.exact_total(column) for column in before.material.columns])
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertEqual(after.material.ages_s(self.end)['inherited-east'], self.ages)

    def test_refining_with_a_new_seam_vertex_conserves_and_keeps_cohorts(self):
        refine = self.control['refine']
        first, second = refine['faces']
        (i, j), (k, m) = refine['seam']
        ends = (F.vertex(i, j), F.vertex(k, m))
        network = self.state.network
        lookup = {name: index for index, name in enumerate(network.vertex_ids)}
        a, b = (network.vertex_direction[lookup[name]] for name in ends)
        middle = (a+b)/np.linalg.norm(a+b)                              # on the seam's own great-circle arc

        def with_vertex(ring):
            ring = list(ring)
            at = next(n for n in range(len(ring)) if {ring[n], ring[(n+1) % len(ring)]} == set(ends))
            return tuple(ring[:at+1]+[refine['new_vertex']]+ring[at+1:])

        faces = {face.face_id: face for face in network.faces}
        for name in (first, second):
            faces[name] = S.Face(name, faces[name].plate_id, with_vertex(faces[name].vertex_ids))
        mesh = T.Mesh(tuple(faces.values()), {refine['new_vertex']: tuple(middle)})
        step = T.advance(self.state, still(network, mesh=mesh), end_time_s=self.end)
        refined = step.state
        before = [self.state.material.exact_total(column) for column in self.state.material.columns]
        self.assertEqual(len(refined.network.vertex_ids), len(network.vertex_ids)+1)
        self.assertEqual(len(step.map.mesh_rows), 2)                     # each face maps onto itself, whole
        self.assertEqual(declared_and_supplied(refined.material), before)
        self.assertEqual(refined.material.cohorts, self.state.material.cohorts)
        # Then split the first face through the new vertex: its accounts divide, exactly, and its cohort stays.
        ring = refined.network.face(first).vertex_ids
        at, corner = ring.index(refine['new_vertex']), ring.index(F.vertex(i, j-1))
        low, high = sorted((at, corner))
        faces = {face.face_id: face for face in refined.network.faces}
        del faces[first]
        for name, part in ((first+'-x', ring[low:high+1]), (first+'-y', ring[high:]+ring[:low+1])):
            faces[name] = S.Face(name, 'east', tuple(part))
        again = T.advance(refined, still(refined.network, 1, 2, mesh=T.Mesh(tuple(faces.values()))),
                          end_time_s=2*self.end).state
        self.assertEqual(declared_and_supplied(again.material), before)
        self.assertTrue(again.material.closure()['identity_exact'])
        for name in (first+'-x', first+'-y'):
            self.assertEqual(again.material.face_cohorts(name), ('inherited-east',))
        self.assertEqual(again.material.ages_s(self.end)['inherited-east'], self.ages)
        # An added vertex that no face uses, or one that reuses an identity, is refused.
        with self.assertRaises(T.TransferRefused):
            T.advance(self.state, still(network, mesh=T.Mesh(tuple(network.faces), {F.vertex(1, 1): tuple(middle)})),
                      end_time_s=self.end)

    def test_malformed_meshes_raise_the_package_errors(self):
        faces = tuple(self.state.network.faces)
        for vertices in (None, 5, 'text', {'new': (1., 0.)}, {'new': None}, (('new', (1., 0., 0.)), 5)):
            with self.assertRaises(TectonicsError, msg=repr(vertices)):
                T.Mesh(faces, vertices)
        for bad in (lambda: T.Mesh(faces+(5,)), lambda: T.Mesh(()), lambda: T.Mesh('faces'),
                    lambda: S.Face('f', 'east', ('a', 'b', 'c'), holes=(None,))):
            with self.assertRaises(TectonicsError):
                bad()
        # A vertex that the mesh adds and no face uses is not a declaration of anything: refused, not ignored.
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(self.state, still(self.state.network, mesh=T.Mesh(faces, {'unused': (0., 0., 1.)})),
                      end_time_s=self.end)
        self.assertIn('no face uses', str(caught.exception))
        # Where a ring starts, and a direction that is not yet a unit vector, do not change a mesh's identity.
        turned = tuple(S.Face(f.face_id, f.plate_id, f.vertex_ids[1:]+f.vertex_ids[:1], f.holes, f.block_id)
                       for f in faces)
        self.assertEqual(T.Mesh(turned).mesh_id, T.Mesh(faces).mesh_id)
        self.assertEqual(T.Mesh(faces, {'new': (0., 0., 2.)}).mesh_id, T.Mesh(faces, {'new': (0., 0., 1.)}).mesh_id)

    def test_a_mesh_cannot_move_or_subdivide_a_physical_interface(self):
        # Moving a seam vertex that lies on the ridge record changes the boundary chain: refused.
        nudged = F.direction(*self.control['nudged_ridge_vertex_deg'])
        state = self.state
        faces = [S.Face(f.face_id, f.plate_id, tuple('ridge-moved' if v == F.vertex(0, 1) else v
                                                     for v in f.vertex_ids)) for f in state.network.faces]
        with self.assertRaises(T.TransferRefused):
            T.advance(state, still(state.network, mesh=T.Mesh(tuple(faces), {'ridge-moved': nudged})),
                      end_time_s=self.end)
        # A face handed to the other plate is not a mesh change.
        swapped = [S.Face(f.face_id, 'west' if f.face_id == 's01-b01' else f.plate_id, f.vertex_ids)
                   for f in state.network.faces]
        with self.assertRaises(T.TransferRefused):
            T.advance(state, still(state.network, mesh=T.Mesh(tuple(swapped))), end_time_s=self.end)
        # A mesh that leaves a hole is not a closed network.
        with self.assertRaises(T.TransferRefused):
            self.remeshed(dict(remove=('s01-b01',)))
        with self.assertRaises(T.TransferRefused):
            self.remeshed(dict(add=(S.Face('extra', 'east', (F.vertex(1, 1), F.vertex(2, 1), 'nowhere')),)))

    def test_mesh_change_together_with_motion(self):
        states, _ = staged_lune()
        moved = states[1]
        end = sum(D3['stages_Myr'])*MYR
        east, west = stage_rotations(1)
        # After the first stage, merge two of the freshly born eastern strips into one face.
        first, second = self.control['merged_strips']
        self.assertEqual(len(moved.network.face(first).vertex_ids), 4)
        plain = T.advance(moved, lune_motion(1, east, west), end_time_s=end).state
        faces = {f.face_id: f for f in plain.network.faces}
        a, b = faces.pop(first), faces.pop(second)
        shared = set(a.vertex_ids) & set(b.vertex_ids)
        self.assertEqual(len(shared), 2)
        start = next(i for i, v in enumerate(a.vertex_ids) if v in shared and a.vertex_ids[i-1] not in shared)
        ring = list(a.vertex_ids[start:]+a.vertex_ids[:start])           # shared, shared, own, own
        own_b = [v for v in b.vertex_ids if v not in shared]
        position = b.vertex_ids.index(ring[0])
        tail = [b.vertex_ids[(position+k) % 4] for k in range(4) if b.vertex_ids[(position+k) % 4] in own_b]
        merged = S.Face('stage-1-merged', 'east', tuple([ring[1]]+ring[2:]+[ring[0]]+tail))
        faces[merged.face_id] = merged
        step = T.advance(moved, lune_motion(1, east, west, mesh=T.Mesh(tuple(faces.values()))), end_time_s=end)
        after = step.state
        self.assertEqual(len(after.network.face_ids), len(plain.network.face_ids)-1)
        self.assertEqual(after.material.face_cohorts('stage-1-merged'), ('boundary-m00|right|0-1',))
        self.assertEqual(after.material.supplied(), plain.material.supplied())       # the same physical transfers
        # The same declared-plus-supplied totals exactly; only the booked rounding of the regrouped pieces differs.
        self.assertEqual(declared_and_supplied(after.material), declared_and_supplied(plain.material))
        self.assertTrue(after.material.closure()['identity_exact'])
        ages = F.control('d3_lune')['expects']['cohort_ages_at_end_myr'][0]
        self.assertEqual(after.material.ages_s(end)['boundary-m00|right|0-1'], (ages[0]*MYR, ages[1]*MYR))


class PreparedMapTests(unittest.TestCase):
    control = F.control('prepared_map')

    def test_a_prepared_map_is_reused_only_while_every_geometry_identity_matches(self):
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(TURN)
        first = T.advance(state, motion, end_time_s=MYR)
        again = T.advance(state, motion, end_time_s=MYR, prepared=first.map)
        self.assertEqual((again.state.state_id, again.map.map_id), (first.state.state_id, first.map.map_id))
        self.assertEqual(again.record(), first.record())
        # Another geometry: the same world with one latitude moved.
        other = F.crust(F.three_plates(latitudes_deg=F.moved_latitudes()))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(other, motion, end_time_s=MYR, prepared=first.map)
        self.assertIn('stale geometry identity', str(caught.exception))
        # Another motion on the same parent geometry.
        with self.assertRaises(T.TransferRefused):
            T.advance(state, F.one_plate_motion(self.control['slower_deg']), end_time_s=MYR, prepared=first.map)
        # The successor's geometry is not its parent's: the first step's map is stale for the second.
        with self.assertRaises(T.TransferRefused):
            T.advance(first.state, F.one_plate_motion(TURN, step=1), end_time_s=2*MYR, prepared=first.map)
        with self.assertRaises(T.TransferRefused):
            T.advance(state, motion, end_time_s=MYR, prepared=first.record()['map'])
        with self.assertRaises(TypeError):
            T.OverlapMap()
        with self.assertRaises(TypeError):
            T.Step()

    def test_transport_port_refusals_carry_their_codes(self):
        # The three refusals the transport port names are told apart by a code, not by parsing a sentence.
        self.assertEqual((T.UNRESOLVED_OVERLAP, T.INCOMPATIBLE_SUPPORT, T.STALE_GEOMETRY),
                         ('unresolved overlap', 'incompatible support', 'stale geometry identity'))
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(TURN)
        first = T.advance(state, motion, end_time_s=MYR)

        def code(call):
            with self.assertRaises(T.TransferRefused) as caught:
                call()
            if caught.exception.code is not None:
                self.assertIn(caught.exception.code, str(caught.exception))    # the reason names its code too
            return caught.exception.code

        other = F.crust(F.three_plates(latitudes_deg=F.moved_latitudes()))
        self.assertEqual(code(lambda: T.advance(other, motion, end_time_s=MYR, prepared=first.map)),
                         T.STALE_GEOMETRY)
        rows = first.map._motion
        index = next(i for i, d in enumerate(rows.donor) if d >= 0 and rows.receiver[i] >= 0)
        smaller = list(rows.area_m2)
        smaller[index] *= self.control['forged_row_factor']
        forged = T._map(state.network, first.state.network, first.state.network, motion,
                        T._Rows(rows.donor, rows.receiver, rows.party, tuple(smaller), rows.parties), None)
        self.assertEqual(code(lambda: T.advance(state, motion, end_time_s=MYR, prepared=forged)),
                         T.UNRESOLVED_OVERLAP)
        other_phase = F.both_sides('boundary-m02', mass_per_area_kg_m2={'basalt': 1.}, thickness_m={'basalt': 1.})
        self.assertEqual(code(lambda: T.advance(state, F.one_plate_motion(TURN, supplies=other_phase),
                                                end_time_s=MYR)), T.INCOMPATIBLE_SUPPORT)
        no_heat = F.both_sides('boundary-m02', enthalpy_per_area_j_m2=None)
        self.assertEqual(code(lambda: T.advance(state, F.one_plate_motion(TURN, supplies=no_heat),
                                                end_time_s=MYR)), T.INCOMPATIBLE_SUPPORT)
        # Any other refusal carries no port code.
        closing = F.control('motion_refusals')['closing_ridge_deg']
        self.assertIsNone(code(lambda: T.advance(state, F.one_plate_motion(closing), end_time_s=MYR)))

    def test_a_map_with_rows_between_faces_that_cannot_overlap_is_refused(self):
        # Two cells of the subducting plate that do not touch exchange a quarter of their own rows. Every donor,
        # receiver and trench sum is unchanged, so only the geometry can say that these rows describe no overlap.
        forged = self.control['forged_exchange']
        state = F.crust(F.three_plates(), cohort_of=lambda face_id: 'c-'+face_id)
        motion = F.one_plate_motion(TURN)
        honest = T.advance(state, motion, end_time_s=MYR)
        rows = honest.map._motion
        old = {name: i for i, name in enumerate(state.network.face_ids)}
        new = {name: i for i, name in enumerate(honest.state.network.face_ids)}
        first, second = forged['faces']
        own = {name: next(i for i, (d, r) in enumerate(zip(rows.donor, rows.receiver))
                          if d == old[name] and r == new[name]) for name in (first, second)}
        moved = forged['fraction']*min(rows.area_m2[own[first]], rows.area_m2[own[second]])
        areas = list(rows.area_m2)
        for name in (first, second):
            areas[own[name]] -= moved
        donor = rows.donor+(old[first], old[second])
        receiver = rows.receiver+(new[second], new[first])
        changed = T._Rows(donor, receiver, rows.party+(-1, -1), tuple(areas)+(moved, moved), rows.parties)
        network = honest.state.network
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=MYR, prepared=T._map(state.network, network, network, motion,
                                                                     changed, None))
        self.assertEqual(caught.exception.code, T.UNRESOLVED_OVERLAP)
        self.assertIn('cannot overlap', str(caught.exception))

    def test_rows_that_each_pass_the_audit_but_together_miss_a_face_are_an_unresolved_overlap(self):
        # One cell's own row is lengthened and its consumption row shortened, each by less than the tolerance of the
        # sums the audit checks. Every audited sum still passes, yet the pieces delivered to the endpoint face miss
        # its measured area by nearly twice the tolerance. That is the port's unresolved overlap.
        stacked = self.control['stacked_closure']
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(TURN)
        honest = T.advance(state, motion, end_time_s=MYR)
        rows = honest.map._motion
        old = state.network.face_ids.index(stacked['face'])
        new = honest.state.network.face_ids.index(stacked['face'])
        own = next(i for i, (d, r) in enumerate(zip(rows.donor, rows.receiver)) if d == old and r == new)
        lost = next(i for i, (d, r) in enumerate(zip(rows.donor, rows.receiver)) if d == old and r < 0)
        part = stacked['fraction_of_relative']*RELATIVE
        longer = part*float(honest.state.network.face_area_m2[new])
        shorter = part*float(state.network.face_area_m2[old])
        areas = list(rows.area_m2)
        areas[own] += longer
        areas[lost] -= longer+shorter
        # Preserve the trench's stricter swept-area total by making the reverse perturbation at another donor.
        other_lost = next(i for i, d in enumerate(rows.donor) if d >= 0 and d != old and rows.receiver[i] < 0
                          and float(state.network.face_area_m2[d])*RELATIVE > shorter
                          and any(source == d and target >= 0 and
                                  float(honest.state.network.face_area_m2[target])*RELATIVE > longer
                                  for source, target in zip(rows.donor, rows.receiver)))
        other_own = next(i for i, (d, r) in enumerate(zip(rows.donor, rows.receiver))
                         if d == rows.donor[other_lost] and r >= 0 and
                         float(honest.state.network.face_area_m2[r])*RELATIVE > longer)
        areas[other_own] -= longer
        areas[other_lost] += longer+shorter
        network = honest.state.network
        forged = T._map(state.network, network, network, motion,
                        T._Rows(rows.donor, rows.receiver, rows.party, tuple(areas), rows.parties), None)
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=MYR, prepared=forged)
        self.assertIn('do not occupy', str(caught.exception))              # every audited sum passed
        self.assertEqual(caught.exception.code, T.UNRESOLVED_OVERLAP)

    def test_a_map_edited_to_lose_material_does_not_close(self):
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(TURN)
        first = T.advance(state, motion, end_time_s=MYR)
        rows = first.map._motion
        index = next(i for i, d in enumerate(rows.donor) if d >= 0 and rows.receiver[i] >= 0)
        smaller = list(rows.area_m2)
        smaller[index] *= self.control['forged_row_factor']
        forged = T._map(state.network, first.state.network, first.state.network, motion,
                        T._Rows(rows.donor, rows.receiver, rows.party, tuple(smaller), rows.parties), None)
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=MYR, prepared=forged)
        self.assertIn('unresolved overlap', str(caught.exception))
        self.assertIn('its overlap rows sum to', str(caught.exception))    # refused by the audit, before any transfer


class ResourceTests(unittest.TestCase):
    """The declared caps: every step control fits the case's work budget; less, or a cancellation, refuses."""

    def setUp(self):
        self.state = F.crust(F.three_plates())
        self.motion = F.one_plate_motion(TURN)

    def test_the_step_controls_fit_their_declared_budget_and_return_every_reservation(self):
        budget = F.budget()
        capped = T.advance(self.state, self.motion, end_time_s=MYR, budget=budget)
        self.assertEqual(capped.state.state_id, T.advance(self.state, self.motion, end_time_s=MYR).state.state_id)
        staged_lune(F.TILT, budget=budget)
        again = T.advance(self.state, self.motion, end_time_s=MYR, prepared=capped.map, budget=budget)
        self.assertEqual(again.map.map_id, capped.map.map_id)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertTrue(0 < budget.peak_reserved_bytes <= RESOURCES['work_budget_bytes'])
        self.assertEqual(budget.statistics()['refusals'], 0)

    def test_a_budget_or_limit_below_the_work_refuses_and_leaves_the_parent_usable(self):
        small = WorkBudget(RESOURCES['refused_budget_bytes'])
        with self.assertRaises(MemoryLimitError):
            T.advance(self.state, self.motion, end_time_s=MYR, budget=small)
        self.assertEqual(small.reserved_bytes, 0)
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(self.state, self.motion, end_time_s=MYR,
                      limits=GeometryLimits(max_vertices=RESOURCES['refused_max_vertices']))
        self.assertIn('envelope exceeded', str(caught.exception))
        self.assertEqual(T.advance(self.state, self.motion, end_time_s=MYR).parent_state_id, self.state.state_id)

    def test_explicit_budget_isolates_motion_mesh_and_restore_from_the_default(self):
        plain = T.advance(self.state, self.motion, end_time_s=MYR)
        face = next(face for face in plain.state.network.faces if len(face.vertex_ids) == 4)
        a, b, c, d = face.vertex_ids
        faces = tuple(item for item in plain.state.network.faces if item.face_id != face.face_id)
        mesh = T.Mesh(faces+(S.Face(face.face_id+'-a', face.plate_id, (a, b, c)),
                             S.Face(face.face_id+'-b', face.plate_id, (a, c, d))))
        for motion in (self.motion, F.one_plate_motion(TURN, mesh=mesh)):
            with self.subTest(mesh=motion.mesh is not None):
                expected = T.advance(self.state, motion, end_time_s=MYR)
                budget, unrelated = F.budget(), WorkBudget(1)
                with mock.patch.object(resources, 'DEFAULT_BUDGET', unrelated):
                    step = T.advance(self.state, motion, end_time_s=MYR, budget=budget)
                    # A cold-cache restore rebuilds the parent too, then applies both material transfers.
                    parent = ({'sphere': self.state.descriptor()}, self.state.arrays())
                    restored = T.restored(parent, {'sphere': step.record(), 'transfers': []}, step.arrays(),
                                          budget=budget)
                self.assertEqual((step.state.state_id, restored.state_id),
                                 (expected.state.state_id, expected.state.state_id))
                self.assertGreater(budget.statistics()['category_peaks']['i03-material'], 0)
                self.assertEqual((budget.reserved_bytes, unrelated.statistics()['refusals']), (0, 0))

    def test_restore_refuses_the_same_insufficient_step_workspace_as_advance(self):
        admitted = F.budget()
        step = T.advance(self.state, self.motion, end_time_s=MYR, budget=admitted)
        metadata, arrays = {'sphere': step.record(), 'transfers': []}, step.arrays()
        # The same moved-network construction must compose with the surrounding step scratch on both paths.
        limit = admitted.peak_reserved_bytes
        for operation in ('advance', 'restore'):
            with self.subTest(operation=operation):
                small = WorkBudget(limit-1)
                with self.assertRaises(MemoryLimitError):
                    if operation == 'advance':
                        T.advance(self.state, self.motion, end_time_s=MYR, budget=small)
                    else:
                        T.restored(self.state, metadata, arrays, budget=small)
                self.assertEqual(small.reserved_bytes, 0)
        budget = WorkBudget(limit)
        restored = T.restored(self.state, metadata, arrays, budget=budget)
        self.assertEqual(restored.state_id, step.state.state_id)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_stops_a_step_at_any_poll_and_issues_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            T.advance(self.state, self.motion, end_time_s=MYR, cancel=cancel)

        class Tripping:
            def __init__(self, trip):
                self.polls, self.trip = 0, trip

            def is_set(self):
                self.polls += 1
                return self.polls >= self.trip

        for trip in RESOURCES['cancel_trip_polls']:
            cancel = Tripping(trip)
            with self.assertRaises(CancelledError):
                T.advance(self.state, self.motion, end_time_s=MYR, cancel=cancel)
            self.assertEqual(cancel.polls, trip)                             # polled throughout the step
        quiet = Tripping(10**9)
        done = T.advance(self.state, self.motion, end_time_s=MYR, cancel=quiet)
        self.assertGreater(quiet.polls, max(RESOURCES['cancel_trip_polls']))
        self.assertEqual(done.parent_state_id, self.state.state_id)           # the parent was never changed


if __name__ == '__main__':
    unittest.main()
