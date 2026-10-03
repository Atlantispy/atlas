"""Focused I03.1 checks: one closed spherical network with uniquely owned faces and separate material accounts.

Small declared sector worlds and an octahedron only: closed coverage and Euler checks, one record per shared
boundary with its sides, junctions, refusals of every unclosed or ambiguous declaration, separate plate and material
identities, frame invariance of measures and adjacency, the separate area, reference-mass, phase-volume and enthalpy
accounts, lossless restoration through the validating constructors, and the declared resource caps. No motion and no
ledger here: those are test_i03_transfer.py and test_i03_ledger.py. Every control value and tolerance is read from
cases/i03_controls_v1.json; the tolerances are the existing W01/W02/I01 ones, checked here against their own files.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import pickle
import sys
import threading
import unittest

import numpy as np

from atlas_tectonics import integration_sphere as S, integration_state as I, integration_transfer as T
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import GeometryLimits
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F

RELATIVE = F.tolerance('relative')
ANGULAR = F.tolerance('angular_absolute_rad')
AREA_CLOSURE_SR = F.tolerance('area_closure_absolute_sr')
SPHERE_M2 = F.SPHERE_M2
STATIC = F.CASE['worlds']['static']
MESH = F.CASE['meshes'][STATIC['mesh']]
IDENTITY = F.control('identity')
RESOURCES = F.CASE['resources']


def sector_parts(**changes):
    """The declaration of the case's static sector world as keyword values, for building refused variants."""
    longitudes, latitudes = F.mesh(STATIC['mesh'])
    plates = tuple(STATIC['plates'])
    vertices, rings = F.sector_mesh(longitudes, latitudes)
    faces = {name: S.Face(name, plates[F.sector_of(name)], ring) for name, ring in rings.items()}
    records = {name: S.Plate(name, F.IDENTITY) for name in sorted(set(plates))}
    boundaries = {}
    for i in range(len(longitudes)):
        west, east = plates[i-1], plates[i]
        if west != east:
            boundaries['boundary-'+F.meridian(i)] = S.Boundary('boundary-'+F.meridian(i), S.RIDGE, west, east,
                                                               F.chain(i, len(latitudes)), F.origin(),
                                                               accretion_fraction=STATIC['accretion_fraction'])
    values = dict(sphere=F.sphere(), vertices=vertices, faces=faces, plates=records, boundaries=boundaries,
                  epoch_id=F.EPOCH, time_s=F.START)
    values.update(changes)
    return values


def build(parts):
    values = dict(parts)
    for key in ('faces', 'plates', 'boundaries'):
        values[key] = tuple(values[key].values())
    return S.build_network(**values)


class CaseTests(unittest.TestCase):
    def test_every_tolerance_of_the_case_is_an_existing_one(self):
        cases = F.CASES
        read = lambda name: json.loads((cases/name).read_text(encoding='utf-8'))
        atlas = read('w01_spherical_atlas.json')['acceptance']
        self.assertEqual(RELATIVE, atlas['relative_tolerance'])
        self.assertEqual(RELATIVE, read('w01_geometry.json')['acceptance']['relative_tolerance'])
        self.assertEqual(RELATIVE, read('w01_boundaries.json')['acceptance']['relative_tolerance'])
        self.assertEqual(RELATIVE, read('w02_completion.json')['verification']['relative_tolerance'])
        self.assertEqual(ANGULAR, atlas['angular_absolute_rad'])
        self.assertEqual(AREA_CLOSURE_SR, atlas['area_closure_absolute_sr'])
        self.assertEqual(F.tolerance('attachment_band_rad'), atlas['source_attachment_rad'])
        self.assertEqual(F.tolerance('attachment_band_rad'), atlas['ambiguity_refusal_rad'])
        self.assertEqual(F.tolerance('junction_algebra_relative'),
                         read('i01_transitions_v1.json')['control_policy']['algebra_relative'])
        self.assertEqual(F.CASE['tolerances']['new'], [])
        # The package uses exactly these values.
        self.assertEqual((S.RELATIVE_TOLERANCE, S.ATTACHMENT_BAND_RAD, T.ALGEBRA_RELATIVE),
                         (RELATIVE, F.tolerance('attachment_band_rad'), F.tolerance('junction_algebra_relative')))

    def test_every_control_names_its_substep_and_only_existing_tolerances(self):
        known = set(F.CASE['tolerances'])-{'new', 'applications'}
        for name, control in F.CASE['controls'].items():
            self.assertIn(control['substep'], ('I03.1', 'I03.2'), name)
            self.assertTrue(set(control['tolerances']) <= known, name)
        self.assertEqual(F.CASE['mode'], T.MODE)
        self.assertLessEqual(F.control('clock_commit')['column_steps'], I.MAX_STEPS)


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = F.sector_world()
        cls.expects = F.control('coverage')['expects']

    def test_closed_sector_world_covers_the_sphere_once(self):
        network = self.network
        self.assertEqual((len(network.face_ids), len(network.vertex_ids), network.plate_ids),
                         (MESH['faces'], MESH['vertices'], ('A', 'B', 'C')))
        stats = network.statistics
        self.assertEqual((stats['euler_characteristic'], stats['unpaired_edges']),
                         (self.expects['euler_characteristic'], self.expects['unpaired_edges']))
        self.assertLessEqual(abs(stats['area_residual_sr']), AREA_CLOSURE_SR)
        areas = network.face_area_m2
        self.assertEqual(areas.shape, (MESH['faces'],))
        self.assertTrue(np.all(areas > 0))
        self.assertLessEqual(abs(math.fsum(areas)-SPHERE_M2), AREA_CLOSURE_SR*F.RADIUS_M**2)
        self.assertLessEqual(abs(network.area_m2-SPHERE_M2), AREA_CLOSURE_SR*F.RADIUS_M**2)
        # Every plate owns two of the six equal sectors: one third of the sphere each, one owner per point.
        for plate, area in network.plate_area_m2().items():
            self.assertLessEqual(abs(area-SPHERE_M2/3), RELATIVE*SPHERE_M2, plate)
        self.assertEqual({network.face_plate(f) for f in network.face_ids if F.sector_of(f) in (2, 3)}, {'B'})
        self.assertEqual(network.face_block('s02-b00'), 'B')            # a block defaults to its plate

    def test_one_record_per_shared_boundary_with_left_and_right(self):
        network = self.network
        self.assertEqual([b.boundary_id for b in network.boundaries], self.expects['boundary_records'])
        record = network.boundary('boundary-m02')
        self.assertEqual((record.kind, record.left_plate_id, record.right_plate_id, record.closed,
                          record.accretion_fraction, record.subducting_side),
                         (S.RIDGE, 'A', 'B', False, STATIC['accretion_fraction'], None))
        self.assertEqual(record.vertex_ids, F.chain(2, 5))
        self.assertEqual((record.origin.kind, record.origin.reference), (S.INITIAL, F.SOURCE))
        self.assertEqual(network.adjacency(), (('A', 'B'), ('A', 'C'), ('B', 'C')))
        # Every edge between two plates lies on exactly one record; seams inside a plate lie on none.
        covered = network.boundary_edges()
        self.assertEqual(sorted(covered), sorted(network.atlas.interplate_edges))
        self.assertEqual(len(covered), self.expects['interplate_edges'])
        self.assertEqual({covered[e] for e in covered}, set(self.expects['boundary_records']))

    def test_poles_are_shared_junctions_in_cyclic_order(self):
        junctions = {j.vertex_id: j for j in self.network.junctions}
        self.assertEqual(sorted(junctions), self.expects['junction_vertices'])
        north, south = junctions['N'], junctions['S']
        self.assertEqual(north.junction_id, 'junction:N')
        self.assertEqual(sorted(north.plate_ids), ['A', 'B', 'C'])
        self.assertEqual(sorted(north.boundary_ends),
                         [('boundary-m00', 'end'), ('boundary-m02', 'end'), ('boundary-m04', 'end')])
        self.assertEqual(sorted(south.boundary_ends),
                         [('boundary-m00', 'start'), ('boundary-m02', 'start'), ('boundary-m04', 'start')])
        # Counter-clockwise about the outward normal at the north pole is eastward: A, B, C in longitude order.
        cycle = north.plate_ids
        start = cycle.index('A')
        self.assertEqual(cycle[start:]+cycle[:start], ('A', 'B', 'C'))
        cycle = south.plate_ids
        start = cycle.index('A')
        self.assertEqual(cycle[start:]+cycle[:start], ('A', 'C', 'B'))

    def test_tilted_axis_gives_the_same_structure_without_frame_poles_or_seams(self):
        tilted = F.sector_world(tilt=F.TILT)
        plain = self.network
        self.assertEqual(tilted.face_ids, plain.face_ids)
        self.assertEqual([j.vertex_id for j in tilted.junctions], [j.vertex_id for j in plain.junctions])
        np.testing.assert_allclose(tilted.face_area_m2, plain.face_area_m2, rtol=RELATIVE, atol=0)
        self.assertNotEqual(tilted.network_id, plain.network_id)
        # Sectors cross the frame's antimeridian and enclose its poles; nothing is special there.
        directions = tilted.vertex_direction
        self.assertTrue(np.all(np.abs(directions[:, 2]) < 1))
        self.assertTrue(np.any(directions[:, 1] < 0) and np.any(directions[:, 1] > 0))

    def test_single_plate_world_has_no_boundary_and_no_junction(self):
        whole = F.octahedron(plates={name: 'only' for name in ('o+++', 'o-++', 'o--+', 'o+-+', 'o++-', 'o-+-',
                                                                 'o---', 'o+--')})
        self.assertEqual((whole.plate_ids, whole.boundaries, whole.junctions), (('only',), (), ()))
        self.assertLessEqual(abs(whole.area_m2-SPHERE_M2), AREA_CLOSURE_SR*F.RADIUS_M**2)

    def test_closed_boundary_loop_has_no_junction(self):
        network = F.octahedron()
        record = network.boundary('equator')
        self.assertEqual((record.closed, record.kind, record.left_plate_id, record.right_plate_id),
                         (True, S.TRANSFORM, 'north', 'south'))
        self.assertEqual(network.junctions, ())
        self.assertEqual(len(network.boundary_edges()), 4)


class TopologyRefusalTests(unittest.TestCase):
    def refused(self, parts, text):
        with self.assertRaises(TectonicsError) as caught:
            build(parts)
        self.assertIn(text, str(caught.exception))

    def test_gap_is_refused_not_closed(self):
        parts = sector_parts()
        del parts['faces']['s03-b01']
        self.refused(parts, 'unpaired seam/gap')

    def test_overlapping_faces_and_duplicate_owners_are_refused(self):
        parts = sector_parts()
        twin = parts['faces']['s03-b01']
        parts['faces']['zz-twin'] = S.Face('zz-twin', twin.plate_id, twin.vertex_ids)
        self.refused(parts, 'duplicate directed edge/same-side ownership')
        parts = sector_parts()
        parts['faces']['zz-twin'] = S.Face('zz-twin', 'C', twin.vertex_ids)
        self.refused(parts, 'duplicate directed edge/same-side ownership')

    def test_t_junction_is_refused(self):
        # One face skips a seam vertex that its neighbours use: the seam subdivisions no longer conform.
        parts = sector_parts()
        merged = S.Face('s03-b01', 'B', (F.vertex(3, 1), F.vertex(4, 1), F.vertex(4, 3), F.vertex(3, 3)))
        parts['faces']['s03-b01'] = merged
        del parts['faces']['s03-b02']
        self.refused(parts, 'unpaired seam/gap')

    def test_duplicate_geometric_vertex_is_refused_not_welded(self):
        # A second vertex at the same place under another name is never merged with the first.
        parts = sector_parts()
        parts['vertices']['copy'] = parts['vertices'][F.vertex(3, 2)]
        self.refused(parts, 'duplicate geometric vertices must use one shared ID')

    def test_pinched_and_reversed_faces_are_refused(self):
        parts = sector_parts()
        face = parts['faces']['s03-b01']
        parts['faces']['s03-b01'] = S.Face(face.face_id, face.plate_id, tuple(reversed(face.vertex_ids)))
        with self.assertRaises(TectonicsError):
            build(parts)
        # A bow-tie ring pinches the face at a point where two of its own edges cross.
        parts = sector_parts()
        parts['faces']['s03-b01'] = S.Face(face.face_id, face.plate_id,
                                           (face.vertex_ids[0], face.vertex_ids[2], face.vertex_ids[1],
                                            face.vertex_ids[3]))
        with self.assertRaises(TectonicsError):
            build(parts)
        # A whole-sphere reversal: every face keeps its interior on the right.
        parts = sector_parts()
        parts['faces'] = {name: S.Face(name, old.plate_id, tuple(reversed(old.vertex_ids)))
                          for name, old in parts['faces'].items()}
        self.refused(parts, 'interior on the left')

    def test_antipodal_edges_and_unused_vertices_are_refused(self):
        parts = sector_parts()
        parts['vertices']['unused'] = (1., 1., 1.)
        self.refused(parts, 'unused registered vertex')
        # Three pole-to-pole lunes: each face spans both poles and fits no open hemisphere.
        vertices = {name: tuple(value) for name, value in
                    F.control('refused_declarations')['unfit_hemisphere_vertices'].items()}
        with self.assertRaises(TectonicsError) as caught:
            S.build_network(sphere=F.sphere(), vertices=vertices,
                            faces=(S.Face('one', 'P', ('N', 'a', 'S', 'b')), S.Face('two', 'P', ('N', 'b', 'S', 'c')),
                                   S.Face('three', 'P', ('N', 'c', 'S', 'a'))),
                            plates=(S.Plate('P', F.IDENTITY),), boundaries=(), epoch_id=F.EPOCH, time_s=F.START)
        self.assertIn('hemisphere', str(caught.exception))


class RecordRefusalTests(unittest.TestCase):
    def refused(self, parts, text):
        """``parts`` is a declaration or a callable building one; the refusal may come from either step."""
        with self.assertRaises(S.SphereError) as caught:
            build(parts() if callable(parts) else parts)
        self.assertIn(text, str(caught.exception))

    def change(self, name, **fields):
        def parts():
            values = sector_parts()
            old = values['boundaries'][name]
            record = dict(boundary_id=old.boundary_id, kind=old.kind, left_plate_id=old.left_plate_id,
                          right_plate_id=old.right_plate_id, vertex_ids=old.vertex_ids, origin=old.origin,
                          closed=old.closed, subducting_side=old.subducting_side,
                          accretion_fraction=old.accretion_fraction)
            record.update(fields)
            values['boundaries'][name] = S.Boundary(**record)
            return values
        return parts

    def test_every_face_owner_is_a_declared_plate_and_every_plate_owns_a_face(self):
        parts = sector_parts()
        del parts['plates']['C']
        self.refused(parts, 'undeclared plate')
        parts = sector_parts()
        parts['plates']['D'] = S.Plate('D', F.IDENTITY)
        self.refused(parts, 'owns no face')

    def test_missing_or_repeated_boundary_record_is_refused(self):
        parts = sector_parts()
        del parts['boundaries']['boundary-m02']
        self.refused(parts, 'has no boundary record')
        parts = sector_parts()
        old = parts['boundaries']['boundary-m02']
        parts['boundaries']['again'] = S.Boundary('again', old.kind, old.left_plate_id, old.right_plate_id,
                                                  old.vertex_ids, old.origin,
                                                  accretion_fraction=old.accretion_fraction)
        self.refused(parts, 'more than one boundary record')

    def test_boundary_sides_must_match_the_faces(self):
        self.refused(self.change('boundary-m02', left_plate_id='B', right_plate_id='A'), 'left and right')
        self.refused(self.change('boundary-m02', vertex_ids=tuple(reversed(F.chain(2, 5)))), 'left and right')
        self.refused(self.change('boundary-m02', right_plate_id='C'), 'left and right')

    def test_boundary_must_follow_shared_edges_between_two_plates(self):
        self.refused(self.change('boundary-m02', vertex_ids=F.chain(1, 5)), 'separates no two plates')
        self.refused(self.change('boundary-m02', vertex_ids=('S', F.vertex(2, 0), F.vertex(2, 2), 'N')),
                     'follows no shared edge')
        self.refused(self.change('boundary-m02', vertex_ids=('S', F.vertex(2, 0))), 'has no boundary record')

    def crossing(self, records):
        """Two plates alternating around the +z vertex of an octahedron above a third: four interfaces meet there."""
        owners = {'o+++': 'L', 'o-++': 'R', 'o--+': 'L', 'o+-+': 'R', 'o++-': 'south', 'o-+-': 'south',
                  'o---': 'south', 'o+--': 'south'}
        equator = (S.Boundary('eq-1', S.TRANSFORM, 'L', 'south', ('+x', '+y'), F.origin()),
                   S.Boundary('eq-2', S.TRANSFORM, 'R', 'south', ('+y', '-x'), F.origin()),
                   S.Boundary('eq-3', S.TRANSFORM, 'L', 'south', ('-x', '-y'), F.origin()),
                   S.Boundary('eq-4', S.TRANSFORM, 'R', 'south', ('-y', '+x'), F.origin()))
        return F.octahedron(plates=owners, boundaries=equator+records)

    def test_a_chain_cannot_run_through_a_junction(self):
        ridge = dict(accretion_fraction=STATIC['accretion_fraction'])
        # Sides stay consistent along each chain, yet both would pass through the vertex where four records meet.
        through = (S.Boundary('cross-1', S.RIDGE, 'L', 'R', ('+y', '+z', '-x'), F.origin(), **ridge),
                   S.Boundary('cross-2', S.RIDGE, 'R', 'L', ('+x', '+z', '-y'), F.origin(), **ridge))
        with self.assertRaises(S.SphereError) as caught:
            self.crossing(through)
        self.assertIn('runs through the junction', str(caught.exception))
        ended = (S.Boundary('arm-1', S.RIDGE, 'L', 'R', ('+y', '+z'), F.origin(), **ridge),
                 S.Boundary('arm-2', S.RIDGE, 'L', 'R', ('+z', '-x'), F.origin(), **ridge),
                 S.Boundary('arm-3', S.RIDGE, 'R', 'L', ('+x', '+z'), F.origin(), **ridge),
                 S.Boundary('arm-4', S.RIDGE, 'R', 'L', ('+z', '-y'), F.origin(), **ridge))
        network = self.crossing(ended)
        top = {j.vertex_id: j for j in network.junctions}['+z']
        self.assertEqual(top.plate_ids, ('R', 'L', 'R', 'L'))
        self.assertEqual(top.boundary_ends, (('arm-1', 'end'), ('arm-2', 'start'), ('arm-4', 'start'),
                                             ('arm-3', 'end')))
        self.assertEqual(len(network.junctions), 5)
        # A chain that returns to its own start is a closed record or two records, never an open one.
        with self.assertRaises(S.SphereError):
            S.Boundary('loop', S.RIDGE, 'L', 'R', ('+y', '+z', '-x', '+y'), F.origin(), **ridge)

    def test_two_plates_can_share_a_closed_boundary_through_both_poles(self):
        # Plate B is one lune; its whole outline is a single closed record with A on the left.
        loop = ('S', *(F.vertex(2, j) for j in range(5)), 'N', *(F.vertex(4, j) for j in reversed(range(5))))
        vertices, rings = F.sector_mesh(*F.mesh(STATIC['mesh']))
        owner = lambda name: 'B' if F.sector_of(name) in (2, 3) else 'A'
        network = S.build_network(
            sphere=F.sphere(), vertices=vertices,
            faces=tuple(S.Face(name, owner(name), ring) for name, ring in rings.items()),
            plates=(S.Plate('A', F.IDENTITY), S.Plate('B', F.IDENTITY)),
            boundaries=(S.Boundary('outline-B', S.RIDGE, 'A', 'B', loop, F.origin(), closed=True,
                                   accretion_fraction=STATIC['accretion_fraction']),),
            epoch_id=F.EPOCH, time_s=F.START)
        self.assertEqual((network.junctions, len(network.boundary_edges())), ((), 12))

    def test_kind_rules_are_declared_not_assumed(self):
        fraction = STATIC['accretion_fraction']
        self.refused(self.change('boundary-m02', accretion_fraction=None), 'accretion fraction')
        self.refused(self.change('boundary-m02', accretion_fraction=1.5), 'accretion fraction')
        self.refused(self.change('boundary-m02', kind=S.TRENCH, accretion_fraction=None), 'subducting side')
        self.refused(self.change('boundary-m02', kind=S.TRENCH, accretion_fraction=fraction,
                                 subducting_side='left'), 'accretion fraction')
        self.refused(self.change('boundary-m02', kind=S.TRANSFORM, accretion_fraction=None,
                                 subducting_side='right'), 'subducting side')
        self.refused(self.change('boundary-m02', kind='suture'), 'boundary kind')
        with self.assertRaises(S.SphereError):
            S.Origin('guessed', F.SOURCE)
        with self.assertRaises(TectonicsError):
            S.Origin(S.EVENT, '')

    def test_retired_identities_stay_reserved(self):
        parts = sector_parts(lineage=S.Lineage(retired_face_ids=('s03-b01',)))
        self.refused(parts, 'retired')
        parts = sector_parts(lineage=S.Lineage(retired_plate_ids=('B',)))
        self.refused(parts, 'retired')
        parts = sector_parts(lineage=S.Lineage(retired_boundary_ids=('boundary-m02',)))
        self.refused(parts, 'retired')
        kept = build(sector_parts(lineage=S.Lineage(retired_face_ids=('long-gone',), retired_plate_ids=('Z',))))
        self.assertEqual(kept.lineage.retired_face_ids, ('long-gone',))

    def test_plate_lineage_must_be_acyclic_and_known(self):
        parts = sector_parts()
        parts['plates']['A'] = S.Plate('A', F.IDENTITY, ('B',))
        parts['plates']['B'] = S.Plate('B', F.IDENTITY, ('A',))
        self.refused(parts, 'cyclic plate lineage')
        parts = sector_parts()
        parts['plates']['A'] = S.Plate('A', F.IDENTITY, ('nobody',))
        self.refused(parts, 'unknown parent plate')
        parts = sector_parts(lineage=S.Lineage(retired_plate_ids=('old',)))
        parts['plates']['A'] = S.Plate('A', F.IDENTITY, ('old',))
        self.assertEqual(build(parts).plate('A').parent_plate_ids, ('old',))

    def test_time_and_labels_are_explicit(self):
        with self.assertRaises(TectonicsError):
            build(sector_parts(time_s=float('nan')))
        with self.assertRaises(TectonicsError):
            build(sector_parts(epoch_id=''))
        with self.assertRaises(S.SphereError):
            build(sector_parts(step=-1))
        with self.assertRaises(S.SphereError):
            build(sector_parts(step=I.MAX_STEPS+1))


class IdentityTests(unittest.TestCase):
    def test_plate_identity_is_separate_from_material_identity(self):
        first = F.sector_world()
        # The same faces regrouped: sector 1 now belongs to B, so the A|B boundary sits on meridian 1.
        second = F.sector_world(plates=tuple(IDENTITY['regrouped_plates']))
        self.assertNotEqual(first.network_id, second.network_id)
        self.assertNotEqual(first.face_plate('s01-b01'), second.face_plate('s01-b01'))
        names = lambda f: 'inherited-crust-%d' % F.sector_of(f)
        one = F.material(first, cohort_of=names)
        two = F.material(second, cohort_of=names)
        self.assertEqual(one.material_id, two.material_id)
        self.assertEqual([c.cohort_id for c in one.cohorts], [c.cohort_id for c in two.cohorts])
        self.assertEqual(one.stock.tobytes(), two.stock.tobytes())
        self.assertNotEqual(S.initial_sphere(first, one).state_id, S.initial_sphere(second, two).state_id)
        # No plate name appears in any material record.
        text = json.dumps(one.descriptor())
        self.assertFalse(any('"%s"' % plate in text for plate in ('A', 'B', 'C')))

    def test_frame_rotation_preserves_measures_and_adjacency(self):
        turned = IDENTITY['plate_rotation']
        network = F.sector_world(rotations={turned['plate']: F.rotation(turned)})
        turn, frame = F.rotation(IDENTITY['frame_rotation']), IDENTITY['frame_rotation']['frame_id']
        moved = S.rotate_frame(network, turn, frame)
        self.assertEqual(moved.sphere.frame_id, frame)
        self.assertEqual((moved.face_ids, moved.vertex_ids, moved.plate_ids),
                         (network.face_ids, network.vertex_ids, network.plate_ids))
        np.testing.assert_allclose(moved.face_area_m2, network.face_area_m2, rtol=RELATIVE, atol=0)
        self.assertLessEqual(abs(moved.area_m2-network.area_m2), RELATIVE*network.area_m2)
        self.assertEqual(moved.adjacency(), network.adjacency())
        self.assertEqual([(b.boundary_id, b.left_plate_id, b.right_plate_id, b.vertex_ids) for b in moved.boundaries],
                         [(b.boundary_id, b.left_plate_id, b.right_plate_id, b.vertex_ids)
                          for b in network.boundaries])
        self.assertEqual([(j.vertex_id, j.plate_ids, j.boundary_ends) for j in moved.junctions],
                         [(j.vertex_id, j.plate_ids, j.boundary_ends) for j in network.junctions])
        self.assertLessEqual(float(np.max(F.angle(moved.vertex_direction, turn.apply(network.vertex_direction)))),
                             ANGULAR)
        # A plate's finite rotation is the same motion expressed in the new axes: Q R Q^-1.
        expected = turn.inverse().then(network.plate(turned['plate']).rotation).then(turn)
        self.assertLessEqual(F.rotation_angle(moved.plate(turned['plate']).rotation, expected), ANGULAR)
        self.assertEqual(moved.plate('A').rotation.quaternion, (1., 0., 0., 0.))
        self.assertLessEqual(abs(moved.statistics['area_residual_sr']), AREA_CLOSURE_SR)
        with self.assertRaises(S.SphereError):
            S.rotate_frame(network, turn, network.sphere.frame_id)

    def test_identity_binds_every_declared_part(self):
        base = F.sector_world()
        self.assertEqual(base.network_id, F.sector_world().network_id)
        small = IDENTITY['small_rotation']
        changed = [F.sector_world(time_s=1.), F.sector_world(step=1), F.sector_world(epoch='another-epoch'),
                   F.sector_world(frame='another-frame'),
                   F.sector_world(rotations={small['plate']: F.rotation(small)}),
                   F.sector_world(kinds={2: dict(kind=S.TRENCH, subducting_side='left')}),
                   F.sector_world(kinds={2: dict(kind=S.RIDGE,
                                                 accretion_fraction=IDENTITY['other_accretion_fraction'])}),
                   F.sector_world(latitudes_deg=F.moved_latitudes()),
                   F.sector_world(lineage=S.Lineage(retired_face_ids=('gone',)))]
        identities = {network.network_id for network in changed}
        self.assertEqual(len(identities), len(changed))
        self.assertNotIn(base.network_id, identities)

    def test_issued_records_are_immutable_and_never_pickled(self):
        network = F.sector_world()
        state = F.state(network)
        for array in (network.vertex_direction, network.face_area_m2, state.material.stock):
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.flags.writeable = True
        for item in (network, state.material, state):
            with self.assertRaises(TypeError):
                pickle.dumps(item)
            self.assertIs(copy.deepcopy(item), item)
        with self.assertRaises(TypeError):
            S.SphereNetwork()
        with self.assertRaises(TypeError):
            S.SphereState()
        with self.assertRaises(Exception):
            network.time_s = 5.
        descriptor = network.descriptor()
        descriptor['plates'][0]['plate_id'] = 'edited'
        self.assertEqual(network.descriptor()['plates'][0]['plate_id'], 'A')


class MaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = F.sector_world()
        cls.material = F.material(cls.network)
        cls.control = F.control('material_accounts')

    def test_area_reference_mass_phase_volume_and_enthalpy_are_separate_accounts(self):
        material = self.material
        self.assertEqual(material.columns, ('area_m2', 'mass_kg:crust', 'mass_kg:mantle-lid', 'volume_m3:crust',
                                            'volume_m3:mantle-lid', 'enthalpy_j'))
        self.assertEqual(material.stock.shape, (MESH['faces'], 6))
        totals = material.totals()
        area = totals['area_m2']
        self.assertLessEqual(abs(area-SPHERE_M2), AREA_CLOSURE_SR*F.RADIUS_M**2)
        for phase in F.PHASES:
            self.assertLessEqual(abs(totals['mass_kg:'+phase]-F.MASS_PER_AREA[phase]*area),
                                 RELATIVE*F.MASS_PER_AREA[phase]*area)
            self.assertLessEqual(abs(totals['volume_m3:'+phase]-F.THICKNESS[phase]*area),
                                 RELATIVE*F.THICKNESS[phase]*area)
        self.assertLess(totals['enthalpy_j'], 0)                    # signed, in its declared basis
        self.assertLessEqual(abs(totals['enthalpy_j']-F.ENTHALPY_PER_AREA*area), RELATIVE*abs(totals['enthalpy_j']))
        self.assertEqual(material.enthalpy_basis, F.BASIS)
        # The exact accounts close exactly: nothing was supplied and nothing rounded since the declaration.
        closure = material.closure()
        self.assertTrue(closure['identity_exact'])
        self.assertEqual(set(closure['residual'].values()), {0.})
        self.assertEqual(material.exact_total('area_m2'), sum((Fraction(float(a)) for a in material.stock[:, 0]),
                                                              Fraction(0)))

    def test_every_piece_names_one_face_and_one_cohort(self):
        material = self.material
        self.assertEqual([c.cohort_id for c in material.cohorts], ['inherited-A', 'inherited-B', 'inherited-C'])
        self.assertEqual(len(material.pieces()), MESH['faces'])
        piece = material.pieces()[0]
        self.assertEqual((piece.face_id, piece.cohort_id), ('s00-b00', 'inherited-A'))
        self.assertEqual(piece.area_m2, float(self.network.face_area_m2[0]))
        self.assertEqual(material.cohort('inherited-B').formation_start_s, None)     # unknown, not zero
        self.assertEqual(material.ages_s(5.)['inherited-B'], None)
        self.assertEqual(set(material.face_cohorts('s02-b01')), {'inherited-B'})

    def test_absent_accounts_are_unknown_not_zero(self):
        bare = F.material(self.network, phases=(), basis=None)
        self.assertEqual(bare.columns, ('area_m2',))
        self.assertIsNone(bare.enthalpy_basis)
        state = S.initial_sphere(self.network, bare)
        unknown = {entry['name'] for entry in state.unknown()}
        self.assertEqual(unknown, {'sphere.reference_mass_kg', 'sphere.phase_volume_m3', 'sphere.enthalpy_j'})
        self.assertNotIn('enthalpy_j', bare.totals())
        full = F.state(self.network)
        self.assertEqual(full.unknown(), [])

    def test_formation_history_is_carried_per_cohort(self):
        dates, now = self.control['dated_cohorts_s'], self.control['query_time_s']
        dated = (F.cohort('inherited-A', start=dates['inherited-A'][0], end=dates['inherited-A'][1]),
                 F.cohort('inherited-B', start=dates['inherited-B'][0], end=dates['inherited-B'][1]),
                 F.cohort('inherited-C', history='i05-history:placeholder'))
        material = F.material(self.network, cohorts=dated)
        self.assertEqual(material.ages_s(now),
                         {'inherited-A': (now-dates['inherited-A'][1], now-dates['inherited-A'][0]),
                          'inherited-B': (now-dates['inherited-B'][1], now-dates['inherited-B'][0]),
                          'inherited-C': None})
        self.assertEqual(material.cohort('inherited-C').history_id, 'i05-history:placeholder')
        with self.assertRaises(S.SphereError):                             # formed after the state's own time
            F.material(self.network, cohorts=(F.cohort('inherited-A', start=1., end=2.),
                                              F.cohort('inherited-B'), F.cohort('inherited-C')))
        with self.assertRaises(S.SphereError):
            F.cohort('late', start=3., end=2.)
        with self.assertRaises(S.SphereError):
            F.cohort('half-known', start=3., end=None)

    def pieces(self, **changes):
        base = {p.face_id: p for p in self.material.pieces()}
        for face, fields in changes.items():
            old = base[face.replace('_', '-')]
            values = dict(face_id=old.face_id, cohort_id=old.cohort_id, area_m2=old.area_m2, mass_kg=old.mass_kg,
                          volume_m3=old.volume_m3, enthalpy_j=old.enthalpy_j)
            values.update(fields)
            base[old.face_id] = S.Piece(**values)
        return tuple(base.values())

    def rebuilt(self, pieces, **changes):
        values = dict(phases=F.PHASES, cohorts=self.material.cohorts, pieces=pieces, enthalpy_basis=F.BASIS)
        values.update(changes)
        return S.build_material(self.network, **values)

    def test_declared_pieces_reproduce_the_areal_material(self):
        self.assertEqual(self.rebuilt(self.pieces()).material_id, self.material.material_id)

    def test_occupancy_must_match_the_measured_support(self):
        shared = self.control['shared_face']
        self.assertEqual(shared, 's03-b01')
        area = float(self.network.face_area_m2[self.network.face_ids.index(shared)])
        with self.assertRaises(S.SphereError) as caught:
            self.rebuilt(self.pieces(s03_b01=dict(area_m2=area*(1+self.control['occupancy_excess_relative']))))
        self.assertIn('measured area', str(caught.exception))
        with self.assertRaises(S.SphereError) as caught:
            self.rebuilt(tuple(p for p in self.pieces() if p.face_id != shared))
        self.assertIn('no material', str(caught.exception))
        # Two cohorts can share a face: their areas partition it.
        part = area*self.control['shared_fraction']
        both = list(self.pieces(s03_b01=dict(area_m2=part, mass_kg=(1., 2.), volume_m3=(3., 4.), enthalpy_j=-1.)))
        both.append(S.Piece(shared, 'inherited-C', area-part, (5., 6.), (7., 8.), 2.))
        both = self.rebuilt(tuple(both))
        self.assertEqual(set(both.face_cohorts(shared)), {'inherited-B', 'inherited-C'})
        self.assertEqual(both.stock.shape, (MESH['faces']+1, 6))

    def test_pieces_together_cover_the_sphere_even_where_faces_are_not_measured_again(self):
        # A computed state's unchanged faces are not measured against their pieces again (integration_transfer).
        # The pieces of every state must still cover the sphere once, within the atlas's own area closure.
        material = self.material
        halved = np.array(material.stock)
        halved[:, 0] /= 2
        exact = tuple(sum((Fraction(float(x)) for x in halved[:, column]), Fraction(0))
                      for column in range(halved.shape[1]))
        zero = (Fraction(0),)*halved.shape[1]
        issue = lambda stock, total, checked: S._material(
            self.network, material.phases, material.enthalpy_basis, material.cohorts, (), None, material.piece_face,
            material.piece_cohort, stock, total, (), zero, zero, None, checked)
        with self.assertRaises(S.SphereError) as caught:
            issue(halved, exact, ())
        self.assertIn('cover the sphere once', str(caught.exception))
        with self.assertRaises(S.SphereError) as caught:
            issue(halved, exact, None)                                     # a declaration measures every face
        self.assertIn('measured area', str(caught.exception))
        whole = tuple(material.exact_total(column) for column in material.columns)
        self.assertEqual(issue(material.stock, whole, ()).material_id, material.material_id)

    def test_invalid_pieces_are_refused(self):
        with self.assertRaises(TectonicsError):
            self.rebuilt(self.pieces(s03_b01=dict(mass_kg=(-1., 2.))))
        with self.assertRaises(TectonicsError):
            self.rebuilt(self.pieces(s03_b01=dict(mass_kg=(1.,))))
        with self.assertRaises(TectonicsError):
            self.rebuilt(self.pieces(s03_b01=dict(enthalpy_j=None)))
        with self.assertRaises(TectonicsError):
            self.rebuilt(self.pieces(s03_b01=dict(enthalpy_j=float('inf'))))
        with self.assertRaises(S.SphereError):
            self.rebuilt(self.pieces(s03_b01=dict(cohort_id='nobody')))
        with self.assertRaises(S.SphereError):
            self.rebuilt(self.pieces(s03_b01=dict(face_id='nowhere')))
        with self.assertRaises(S.SphereError):
            self.rebuilt(self.pieces()+self.pieces()[:1])
        with self.assertRaises(S.SphereError):
            self.rebuilt(self.pieces(), enthalpy_basis=None)
        with self.assertRaises(S.SphereError):
            self.rebuilt(self.pieces(), phases=('mantle-lid', 'crust'))

    def test_exteriors_are_named_sources_or_sinks(self):
        material = F.material(self.network, exteriors=(('slab', 'sink'), ('mantle-source', 'source')))
        self.assertEqual(material.exteriors, (('mantle-source', 'source'), ('slab', 'sink')))
        self.assertNotEqual(material.material_id, self.material.material_id)
        for bad in ((('slab', 'drain'),), (('slab', 'sink'), ('SLAB', 'source')), (('not a token', 'sink'),),
                    (('inherited-A', 'sink'),)):
            with self.assertRaises(TectonicsError):
                F.material(self.network, exteriors=bad)


class PersistenceTests(unittest.TestCase):
    def test_network_material_and_state_restore_exactly_through_their_constructors(self):
        control = F.control('persistence')
        turned, trench = control['plate_rotation'], control['trench']
        network = F.sector_world(tilt=F.TILT, rotations={turned['plate']: F.rotation(turned)},
                                 kinds={trench['meridian']: dict(kind=S.TRENCH,
                                                                 subducting_side=trench['subducting_side'])},
                                 lineage=S.Lineage(retired_face_ids=(control['retired_face'],)))
        state = F.state(network, exteriors=(('slab', 'sink'),))
        record, arrays = state.descriptor(), state.arrays()
        # Schema v2 keeps vertices in plate reference frames (I03a-2 Part 1): homes, references and copies; the
        # material keeps each face's occupancy allowance (I03a-2, D7).
        self.assertEqual(set(arrays), {'sphere.vertex_ids', 'sphere.vertex_home', 'sphere.vertex_reference',
                                       'sphere.view_vertex', 'sphere.view_plate', 'sphere.view_reference',
                                       'sphere.faces', 'sphere.boundaries', 'sphere.cohorts', 'sphere.piece_face',
                                       'sphere.piece_cohort', 'sphere.piece_stock', 'sphere.face_occupancy_allowance'})
        self.assertEqual(json.loads(json.dumps(record)), record)             # plain finite JSON
        again = S.restore_sphere(json.loads(json.dumps(record)), {k: np.array(v) for k, v in arrays.items()})
        self.assertEqual((again.state_id, again.network.network_id, again.material.material_id),
                         (state.state_id, network.network_id, state.material.material_id))
        self.assertEqual(again.issued_by, I.RESTORED)
        self.assertEqual(state.issued_by, I.DECLARED)
        self.assertEqual(again.network.vertex_direction.tobytes(), network.vertex_direction.tobytes())
        self.assertEqual(again.network.plate('B').rotation.quaternion, network.plate('B').rotation.quaternion)
        self.assertEqual(again.network.lineage, network.lineage)
        self.assertEqual(again.material.stock.tobytes(), state.material.stock.tobytes())

    def test_edited_records_and_arrays_are_refused_not_rebound(self):
        state = F.state()
        record, arrays = state.descriptor(), state.arrays()

        def restored(edit):
            changed_record = json.loads(json.dumps(record))
            changed = {k: np.array(v) for k, v in arrays.items()}
            edit(changed_record, changed)
            return S.restore_sphere(changed_record, changed)

        def nudge(r, a):
            a['sphere.vertex_reference'][3] = F.direction(61., -59.)

        def stock(r, a):
            a['sphere.piece_stock'][5, 1] *= 2

        def owner(r, a):
            text = a['sphere.faces'].tobytes().decode().replace('"plate_id":"B"', '"plate_id":"C"', 1)
            a['sphere.faces'] = np.frombuffer(text.encode(), dtype=np.uint8)

        def time(r, a):
            r['network']['time_s'] = 3.

        def missing(r, a):
            del a['sphere.cohorts']

        def identity(r, a):
            r['state_id'] = '0'*64

        def exact(r, a):
            r['material']['exact']['initial'][0] = '1/1'

        edits = (nudge, stock, owner, time, missing, identity, exact)
        self.assertEqual(len(edits), len(F.control('persistence')['edits']))
        for edit in edits:
            with self.assertRaises(TectonicsError, msg=edit.__name__):
                restored(edit)
        self.assertEqual(restored(lambda r, a: None).state_id, state.state_id)


class CatalogueTests(unittest.TestCase):
    def test_every_network_quantity_is_registered_once_in_the_i02_catalogue(self):
        names = [entry[0] for entry in I.CATALOGUE]
        sphere = [name for name in names if name.startswith('sphere.')]
        self.assertEqual(sorted(sphere), sorted(S.QUANTITIES))
        self.assertEqual(len(sphere), len(set(sphere)))
        for name in sphere:
            entry = dict(zip(I.CATALOGUE_FIELDS, I._INDEX[name]))
            self.assertEqual((entry['owner'], entry['status']), (S.OWNER, 'supported'), name)
            self.assertTrue(entry['units'] and entry['support'] and entry['producer'] and entry['meaning'])
        # The column route's own unknown geometric entry is still declared: the strip is not embedded yet.
        self.assertEqual(I._INDEX['global_position'][5], 'unknown')

    def test_declaration_reports_what_this_state_carries(self):
        state = F.state()
        declaration = {entry['name']: entry for entry in state.declaration()}
        self.assertEqual(sorted(declaration), sorted(S.QUANTITIES))
        self.assertTrue(all(entry['known'] for entry in declaration.values()))
        self.assertEqual(declaration['sphere.reference_mass_kg']['units'], 'kg')
        self.assertEqual(state.identities()['catalogue_id'], I.CATALOGUE_ID)
        fields = state.fields()
        self.assertEqual(sorted(fields), sorted(S.FIELDS))
        value = state.field('sphere.face_area_m2')
        self.assertEqual((value['units'], value['support'], value['owner'], value['state_id']),
                         ('m2', 'network face', S.OWNER, state.state_id))
        self.assertEqual(value['values'].tobytes(), state.network.face_area_m2.tobytes())
        with self.assertRaises(S.SphereError):
            state.field('sphere.nothing')


class HardeningTests(unittest.TestCase):
    """Defects found by an independent verifier running the code, each reproduced here before its fix."""

    def linked(self):
        control = F.control('ledger_attachment')
        return F.material(F.sector_world(), phases=tuple(control['linked_material']['phases']),
                          stock_link=dict(control['stock_link']),
                          mass_per_area_kg_m2=dict(control['linked_material']['mass_per_area_kg_m2']),
                          thickness_m=dict(control['linked_material']['thickness_m']))

    def test_a_stock_link_cannot_be_edited_after_issue(self):
        material = self.linked()
        link = F.control('ledger_attachment')['stock_link']
        self.assertEqual(dict(material.stock_link), link)
        with self.assertRaises(TypeError):
            material.stock_link['receives'] = 'undeclared-sink'
        self.assertEqual(dict(material.stock_link), link)
        self.assertEqual(material.descriptor()['stock_link'], link)
        # Finite stocks carry component masses and signed enthalpy: a link without either is not a declaration.
        with self.assertRaises(S.SphereError):
            F.material(F.sector_world(), phases=(), basis=None, stock_link=dict(link))
        with self.assertRaises(S.SphereError):
            F.material(F.sector_world(), basis=None, stock_link=dict(link))

    def test_handed_out_arrays_cannot_reshape_the_issued_state(self):
        state = F.state()
        totals = state.material.totals()
        for name, array in state.arrays().items():
            self.assertIsNot(array, state.arrays()[name], name)              # a fresh view each time
            self.assertFalse(array.flags.writeable, name)
        state.arrays()['sphere.piece_stock'].shape = (-1,)
        state.arrays()['sphere.vertex_reference'].shape = (-1,)
        state.network.arrays()['sphere.faces'].shape = (-1, 1)
        self.assertEqual(state.material.totals(), totals)
        self.assertEqual(state.material.stock.shape, (MESH['faces'], 6))
        self.assertIs(S.verified(state), state)
        self.assertEqual(S.initial_sphere(state.network, state.material).state_id, state.state_id)

    def test_a_forged_attribute_no_longer_matches_its_record(self):
        forgeries = (
            ('network', 'epoch_id', 'another-epoch'), ('network', 'time_s', 5.), ('network', 'step', 3),
            ('network', 'reference_time_s', -1.), ('network', 'plates', ()), ('network', 'boundaries', ()),
            ('network', 'junctions', ()), ('network', 'lineage', S.Lineage(retired_face_ids=('x',))),
            ('network', 'sphere', F.sphere('another-frame')), ('network', '_faces', ()),
            ('network', '_areas', np.zeros(MESH['faces'])), ('network', '_owners', ()),
            ('material', 'cohorts', ()), ('material', 'exteriors', (('slab', 'sink'),)), ('material', 'phases', ()),
            ('material', 'columns', ('area_m2',)), ('material', 'enthalpy_basis', 'another-basis'),
            ('material', 'stock_link', dict(receives='a', returns='b')),
            ('material', '_stock', np.ones((MESH['faces'], 6))), ('material', '_face', np.zeros(MESH['faces'], int)),
            ('material', '_initial', (Fraction(0),)*6), ('material', '_face_ids', ()))
        for target, name, value in forgeries:
            state = F.state()
            object.__setattr__(getattr(state, target), name, value)
            with self.assertRaises(S.SphereError, msg=name):
                S.verified(state)
        state = F.state()
        self.assertIs(S.verified(state), state)

    def test_restoration_refuses_stored_arrays_that_only_cast_to_the_issued_ones(self):
        state = F.state()
        record, arrays = state.descriptor(), state.arrays()

        def text(old, new):
            return lambda a: np.frombuffer(a.tobytes().decode().replace(old, new, 1).encode(), dtype=np.uint8)

        def backwards(a):
            return np.frombuffer(b'\n'.join(reversed(a.tobytes().split(b'\n'))), dtype=np.uint8)

        edits = (('sphere.piece_face', lambda a: a.astype(np.float64)+0.4),
                 ('sphere.piece_cohort', lambda a: a.astype(np.float64)+0.999),
                 ('sphere.piece_face', lambda a: a.astype(np.int32)),
                 ('sphere.piece_stock', lambda a: a+1j*np.arange(a.size).reshape(a.shape)),
                 ('sphere.piece_stock', lambda a: np.array([[repr(float(x)) for x in row] for row in a])),
                 ('sphere.piece_face', lambda a: np.array(['x']*len(a))),
                 ('sphere.vertex_reference', lambda a: a.astype(np.float32)),
                 ('sphere.faces', text('{"block_id"', '{"note":"forged","block_id"')),
                 ('sphere.faces', text('"plate_id":"B"', '"plate_id":"C","plate_id":"B"')),
                 ('sphere.faces', backwards),
                 ('sphere.boundaries', text('"accretion_fraction":0.5', '"accretion_fraction":5e-1')),
                 ('sphere.cohorts', text('{"cohort_id"', '{"aaa":1,"cohort_id"')),
                 ('sphere.faces', lambda a: np.frombuffer(b'['*100000+b']'*100000, dtype=np.uint8)),
                 ('sphere.cohorts', lambda a: np.frombuffer(b'['*100000+b']'*100000, dtype=np.uint8)))
        for name, change in edits:
            changed = {k: np.array(v) for k, v in arrays.items()}
            changed[name] = change(changed[name])
            with self.assertRaises(S.SphereError, msg=name):
                S.restore_sphere(json.loads(json.dumps(record)), changed)
        # Vertex rows and their identities permuted together: the same geometry in another stored order.
        changed = {k: np.array(v) for k, v in arrays.items()}
        changed['sphere.vertex_reference'] = changed['sphere.vertex_reference'][::-1].copy()
        changed['sphere.vertex_ids'] = backwards(changed['sphere.vertex_ids'])
        with self.assertRaises(S.SphereError):
            S.restore_sphere(json.loads(json.dumps(record)), changed)
        same = {k: np.array(v) for k, v in arrays.items()}
        self.assertEqual(S.restore_sphere(record, same).state_id, state.state_id)
        # Arrays of a later step may share the snapshot; a root's snapshot holds the state's arrays and no other.
        more = dict(same, **{'sphere.map_area_m2': np.zeros(3)})
        self.assertEqual(S.restore_sphere(record, more).state_id, state.state_id)
        with self.assertRaises(S.SphereError):
            S.restore_sphere(record, more, exclusive=True)

    def test_accounts_beyond_the_exact_range_are_refused_when_issued(self):
        network = F.sector_world()
        limit = 2.**960
        pieces = tuple(S.Piece(face_id, 'inherited', float(area), (limit if k < 2 else 1.,), (1.,))
                       for k, (face_id, area) in enumerate(zip(network.face_ids, network.face_area_m2)))
        with self.assertRaises(S.SphereError) as caught:
            S.build_material(network, phases=('crust',), cohorts=(F.cohort('inherited'),), pieces=pieces)
        self.assertIn('accounting range', str(caught.exception))
        one = tuple(S.Piece(p.face_id, p.cohort_id, p.area_m2, (limit if k < 1 else 0.,), p.volume_m3)
                    for k, p in enumerate(pieces))
        kept = S.build_material(network, phases=('crust',), cohorts=(F.cohort('inherited'),), pieces=one)
        state = S.initial_sphere(network, kept)
        self.assertEqual(S.restore_sphere(state.descriptor(), state.arrays()).state_id, state.state_id)

    def test_the_junction_pass_draws_on_the_callers_budget_and_limits(self):
        from atlas_tectonics.resources import DEFAULT_BUDGET
        with DEFAULT_BUDGET.reserve(DEFAULT_BUDGET.available_bytes-1024, category='held-by-the-test'):
            network = F.sector_world(budget=F.budget())
        self.assertEqual(len(network.junctions), 2)
        with self.assertRaises(TectonicsError) as caught:
            F.sector_world(limits=GeometryLimits(max_overlay_pairs=6*6-1))     # six edges meet at each pole
        self.assertIn('junction pair limit', str(caught.exception))
        self.assertEqual(len(F.sector_world(limits=GeometryLimits(max_overlay_pairs=6*6)).junctions), 2)

    def test_occupancy_is_summed_the_same_way_wherever_it_is_checked(self):
        # 20,002 pieces that occupy one face exactly; a plain running sum of them is off by more than the tolerance.
        network = F.sector_world()
        face = 's00-b00'
        area = float(network.face_area_m2[network.face_ids.index(face)])
        top = 2.**math.floor(math.log2(area))
        ulp, count = math.ulp(top), 20000
        part = math.floor((area-top)/count/ulp)*ulp+0.4990234375*ulp
        rest = Fraction(area)-Fraction(top)-count*Fraction(part)
        areas = [top]+[part]*count+[float(rest)]
        self.assertEqual(sum(map(Fraction, areas)), Fraction(area))
        running = 0.
        for value in areas:
            running += value
        self.assertGreater(abs(running-area), RELATIVE*area)
        names = ['c%05d' % k for k in range(len(areas))]
        pieces = [S.Piece(face, name, value) for name, value in zip(names, areas)]
        pieces += [S.Piece(other, names[0], float(value)) for other, value in zip(network.face_ids,
                                                                                network.face_area_m2) if other != face]
        material = S.build_material(network, phases=(), cohorts=tuple(F.cohort(name) for name in names),
                                    pieces=tuple(pieces))
        state = S.initial_sphere(network, material)
        self.assertTrue(state.material.closure()['identity_exact'])

    def test_malformed_declarations_raise_the_package_errors(self):
        network = F.sector_world()
        cohorts = (F.cohort('c'),)
        bad = (lambda: S.Face('f', 'P', ('a', 'b', 'c'), holes=(5,)),
               lambda: S.Face('f', 'P', ('a', ['b'], 'c')),
               lambda: S.Face('f', 'P', ('a', 'b')),
               lambda: S.Boundary('b', np.array(['ridge']), 'A', 'B', ('x', 'y'), F.origin(), accretion_fraction=.5),
               lambda: S.Origin(np.array(['event']), 'reference'),
               lambda: F.material(network, exteriors=(('slab', np.array(['sink'])),)),
               lambda: network.face_block(np.array(['s00-b00'])),
               lambda: network.face(['s00-b00']),
               lambda: network.boundary(np.array(['boundary-m00'])),
               lambda: S.build_material(network, phases=(), cohorts=cohorts, pieces=(S.Piece(['s00-b00'], 'c', 1.),)),
               lambda: S.build_material(network, phases=(), cohorts=cohorts, pieces=(S.Piece('s00-b00', ['c'], 1.),)),
               lambda: S.areal_material(network, phases=(), cohorts=cohorts, mass_per_area_kg_m2={}, thickness_m={},
                                        face_cohort={face_id: ['c'] for face_id in network.face_ids}))
        for index, call in enumerate(bad):
            with self.assertRaises(TectonicsError, msg=index):
                call()

    def test_identity_does_not_depend_on_equivalent_spellings(self):
        # A closed chain names a loop: where it starts is not part of the declaration.
        loop, identities = ('+x', '+y', '-x', '-y'), set()
        for start in range(4):
            chain = loop[start:]+loop[:start]
            record = S.Boundary('equator', S.TRANSFORM, 'north', 'south', chain, F.origin(), closed=True)
            identities.add(F.octahedron(boundaries=(record,)).network_id)
        self.assertEqual(len(identities), 1)
        # Parents are a set; minus zero is zero.
        lineage = S.Lineage(retired_plate_ids=('X', 'Y'))
        parts = sector_parts(lineage=lineage)
        one, two = dict(parts['plates']), dict(parts['plates'])
        one['A'], two['A'] = S.Plate('A', F.IDENTITY, ('X', 'Y')), S.Plate('A', F.IDENTITY, ('Y', 'X'))
        self.assertEqual(build(dict(parts, plates=one)).network_id, build(dict(parts, plates=two)).network_id)
        self.assertEqual(F.sector_world(time_s=-0.).network_id, F.sector_world(time_s=0.).network_id)
        parts, signed = sector_parts(), sector_parts()
        signed['vertices'] = {name: tuple(-0. if x == 0 else x for x in value)
                              for name, value in signed['vertices'].items()}
        self.assertEqual(build(signed).network_id, build(parts).network_id)
        fixed = lambda value: F.sector_world(kinds={2: dict(kind=S.RIDGE, accretion_fraction=value)}).network_id
        self.assertEqual(fixed(-0.), fixed(0.))
        dated = lambda value: F.material(F.sector_world(), cohorts=(
            F.cohort('inherited-A', start=value, end=value), F.cohort('inherited-B'), F.cohort('inherited-C')))
        self.assertEqual(dated(-0.).material_id, dated(0.).material_id)


class ResourceTests(unittest.TestCase):
    """The declared caps: a build and its material fit the case's work budget; less, or a cancellation, refuses."""

    def test_a_build_fits_its_declared_budget_and_returns_every_reservation(self):
        budget = F.budget()
        network = F.sector_world(tilt=F.TILT, budget=budget)
        state = F.state(network, budget=budget)
        again = S.restore_sphere(state.descriptor(), state.arrays(), budget=budget)
        self.assertEqual(again.state_id, state.state_id)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertTrue(0 < budget.peak_reserved_bytes <= RESOURCES['work_budget_bytes'])
        self.assertEqual(budget.statistics()['refusals'], 0)

    def test_a_budget_or_limit_below_the_work_refuses_before_anything_is_issued(self):
        small = WorkBudget(RESOURCES['refused_budget_bytes'])
        with self.assertRaises(MemoryLimitError):
            F.sector_world(budget=small)
        self.assertEqual((small.reserved_bytes, small.statistics()['refusals']), (0, 1))
        network = F.sector_world()
        with self.assertRaises(MemoryLimitError):
            F.material(network, budget=WorkBudget(1024))
        with self.assertRaises(TectonicsError) as caught:
            F.sector_world(limits=GeometryLimits(max_vertices=RESOURCES['refused_max_vertices']))
        self.assertIn('envelope exceeded', str(caught.exception))
        with self.assertRaises(TectonicsError):
            F.sector_world(limits=dict(max_vertices=10**6))                 # limits are typed, never a bare mapping
        with self.assertRaises(TypeError):
            F.sector_world(budget=10**9)

    def test_cancellation_stops_a_build_and_a_restoration(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            F.sector_world(cancel=cancel)
        state = F.state()
        with self.assertRaises(CancelledError):
            S.restore_sphere(state.descriptor(), state.arrays(), cancel=cancel)

        class Tripping:
            def __init__(self, trip):
                self.polls, self.trip = 0, trip

            def is_set(self):
                self.polls += 1
                return self.polls >= self.trip

        for trip in RESOURCES['cancel_trip_polls']:
            cancel = Tripping(trip)
            with self.assertRaises(CancelledError):
                F.sector_world(cancel=cancel)
            self.assertEqual(cancel.polls, trip)                             # polled inside the build, not only first
        with self.assertRaises(TectonicsError):
            F.sector_world(cancel=object())                                  # a cancel provides is_set()


if __name__ == '__main__':
    unittest.main()
