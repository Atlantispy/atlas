"""I03 stage finish: rotated coordinates and different sampling meshes represent the same case. WORKING NON-CANON.

E1 and E2 of the I03b bounds proposal (3 October 2026). They compare only what I03 transfers, on supports common to
both runs: I03 reconstructs no field, so the distribution of a cohort within a plate is not compared. Every value comes
from cases/i03_controls_v3.json (equivalence_rotated, equivalence_meshes). The coordinator approved E1-E3 on 3 October
2026, E2 with a correction: per-cohort totals are compared only where consumption cannot mix cohorts, a premise the
mesh test checks, and per-trench consumed totals are compared besides.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import json
import math
import unittest
from unittest import mock

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_events as E, integration_sphere as S, integration_transfer as T
from atlas_tectonics.kinematics import Rotation

CASE3 = json.loads((F.CASES/'i03_controls_v3.json').read_text(encoding='utf-8'))
RELATIVE = F.tolerance('relative')
MYR = F.MYR_S


def control(name):
    return CASE3['controls'][name]


def close(test, value, expected, label):
    value, expected = float(value), float(expected)
    if expected == 0:
        test.assertEqual(value, 0., label)
    else:
        test.assertLessEqual(abs(value-expected), RELATIVE*abs(expected), (label, value, expected))


def area_over_perimeter(network, index):
    """A face's area over its perimeter in rad, as the C7 range measures it (integration_transfer)."""
    rings = network.face_coordinates(index)
    perimeter = math.fsum(float(T._angle(a, b)) for ring in rings for a, b in zip(ring, np.roll(ring, -1, axis=0)))
    return float(network.face_area_m2[index])/network.sphere.radius_m**2/perimeter


def by_plate(state):
    """{plate: [area, column totals...]} from the pieces."""
    material, network = state.material, state.network
    out = {}
    for row in range(len(material.piece_face)):
        plate = network.faces[int(material.piece_face[row])].plate_id
        out.setdefault(plate, [Fraction(0)]*len(material.columns))
        for k, value in enumerate(material.stock[row]):
            out[plate][k] += Fraction(float(value))
    return out


def by_cohort(state, rename=lambda name: name):
    material = state.material
    out = {}
    for row in range(len(material.piece_face)):
        name = rename(material.cohorts[int(material.piece_cohort[row])].cohort_id)
        out.setdefault(name, [Fraction(0)]*len(material.columns))
        for k, value in enumerate(material.stock[row]):
            out[name][k] += Fraction(float(value))
    return out


def jump_history(tilt=None):
    """event_closed_sphere's history: three intervals, the second ending with the ridge jump."""
    rule, jumped = control('event_closed_sphere'), control('event_ridge_jump')
    turn = rule['turn_deg']
    slice_, east = tuple(jumped['split']['parts'])
    grown = jumped['merge']['new_plate']
    states = [F.crust(F.three_plates(tilt=tilt))]
    states.append(T.advance(states[0], F.one_plate_motion(turn, tilt=tilt), end_time_s=MYR).state)
    endpoint = T.advance(states[1], F.one_plate_motion(turn, step=1, tilt=tilt), end_time_s=2*MYR).state.network
    west = tuple(sorted(f.face_id for f in endpoint.faces if f.plate_id == 'A' and not f.face_id.startswith('s03-')))
    eastern = tuple(sorted(f.face_id for f in endpoint.faces if f.plate_id == 'A' and f.face_id.startswith('s03-')))
    chain = ('S',)+tuple(F.vertex(3, j) for j in range(5))+('N',)
    split = E.Split(jumped['split']['event_id'], 'A', ((slice_, west), (east, eastern)),
                    S.Boundary(jumped['split']['boundary_id'], S.RIDGE, slice_, east, chain,
                               S.Origin(S.EVENT, jumped['split']['event_id']), accretion_fraction=.5), endpoint.time_s)
    jump = E.RidgeJump('jump', split, E.Merge(jumped['merge']['event_id'], tuple(jumped['merge']['plates']), grown,
                                              endpoint.time_s))
    states.append(T.advance(states[1], F.one_plate_motion(turn, step=1, tilt=tilt, events=(jump,)),
                            end_time_s=2*MYR).state)
    follow = T.Motion(2, 3, {east: F.spin(turn, tilt), 'B': F.IDENTITY, grown: F.IDENTITY},
                      supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
    states.append(T.advance(states[2], follow, end_time_s=3*MYR).state)
    return states


class RotatedTests(unittest.TestCase):
    def test_the_same_history_in_tilted_axes_gives_the_same_accounts(self):
        plain, tilted = jump_history(), jump_history(F.TILT)
        for a, b in zip(plain, tilted):
            self.assertTrue(a.material.closure()['identity_exact'] and b.material.closure()['identity_exact'])
            self.assertEqual(a.network.face_ids, b.network.face_ids)
            for k, name in enumerate(a.network.face_ids):
                self.assertGreater(area_over_perimeter(a.network, k), 2*T.THIN_FACE_RATIO, name)   # E1's 1e-12 case
                close(self, b.network.face_area_m2[k], a.network.face_area_m2[k], name)
            for scope, one, two in (('plate', by_plate(a), by_plate(b)), ('cohort', by_cohort(a), by_cohort(b))):
                self.assertEqual(sorted(one), sorted(two))
                for name in one:
                    for k, column in enumerate(a.material.columns):
                        close(self, two[name][k], one[name][k], (scope, name, column))
            sa, sb = a.material.supplied(), b.material.supplied()
            self.assertEqual(sorted(sa), sorted(sb))
            for name in sa:
                for column in sa[name]:
                    close(self, sb[name][column], sa[name][column], (name, column))


class MeshTests(unittest.TestCase):
    """E2 as corrected: every mesh here is in the single-cohort-consumption class, a premise checked on each."""

    def history(self, world, ridge, trench, rule=None, compact=True):
        rule = rule or control('equivalence_meshes')
        states = [F.crust(world)]
        for k in range(rule['intervals']):
            motion = F.one_plate_motion(rule['turn_deg'], step=k, ridge=ridge, trench=trench)
            step = T.advance(states[-1], motion, end_time_s=(k+1)*MYR)
            self.assert_single_cohort_consumption(states[-1], step, trench)
            states.append(step.state)
            if compact:                                  # the precondition of the 1e-12 comparison (round 1)
                for i, name in enumerate(step.state.network.face_ids):
                    self.assertGreater(area_over_perimeter(step.state.network, i), 2*T.THIN_FACE_RATIO, name)
        return states[-1]

    def assert_single_cohort_consumption(self, parent, step, trench):
        """The faces the step books to the trench (its consumed region) held only cohort inherited-A."""
        consumed = {row[0] for row in step.map.rows if row[1] == -1 and row[2] == 'trench|'+trench}
        self.assertTrue(consumed)
        material = parent.material
        held = {material.cohorts[int(material.piece_cohort[row])].cohort_id
                for row in range(len(material.piece_face)) if int(material.piece_face[row]) in consumed}
        self.assertEqual(held, {'inherited-A'}, 'the premise of the single-cohort-consumption class fails')

    def compare(self, coarse, other, names):
        role = lambda name: '|'.join(names.get(token, token) for token in name.split('|'))
        self.assertEqual(coarse.material.columns, other.material.columns)
        for column in coarse.material.columns:
            close(self, other.material.exact_total(column), coarse.material.exact_total(column), ('global', column))
        for scope, one, two in (('plate', by_plate(coarse), by_plate(other)),
                                ('cohort', by_cohort(coarse), by_cohort(other, role))):
            self.assertEqual(sorted(one), sorted(two))
            for name in one:
                for k, column in enumerate(coarse.material.columns):
                    close(self, two[name][k], one[name][k], (scope, name, column))
        sa = coarse.material.supplied()
        sb = {role(name): values for name, values in other.material.supplied().items()}
        self.assertEqual(sorted(sa), sorted(sb))
        for name in sa:                                  # every named exterior transfer, matched by role
            for column in sa[name]:
                close(self, sb[name][column], sa[name][column], (name, column))
        # Per trench: the consumed area and the consumed amounts, booked to the slab.
        close(self, sb['trench|boundary-m04']['area_m2'], sa['trench|boundary-m04']['area_m2'], 'consumed area')
        for column in sa['slab']:
            close(self, sb['slab'][column], sa['slab'][column], ('consumed', column))
        rule = control('equivalence_meshes')
        born = F.lune(rule['turn_deg']/2*rule['intervals'])
        for side in ('left', 'right'):
            close(self, sb['ridge|boundary-m02|'+side]['area_m2'], born, ('lune', side))

    def test_a_nested_refinement_and_a_non_nested_mesh_give_the_same_totals(self):
        rule = control('equivalence_meshes')
        coarse = self.history(F.three_plates(), 'boundary-m02', 'boundary-m04')
        born = F.lune(rule['turn_deg']/2*rule['intervals'])
        for side in ('left', 'right'):
            close(self, coarse.material.supplied()['ridge|boundary-m02|'+side]['area_m2'], born, ('lune', side))
        for prefix, ridge, trench in (('refined', 'boundary-m04', 'boundary-m08'),
                                      ('non_nested', 'boundary-m03', 'boundary-m06')):
            with self.subTest(mesh=prefix):
                world = F.three_plates(longitudes_deg=tuple(rule[prefix+'_longitudes_deg']),
                                       latitudes_deg=tuple(rule[prefix+'_latitudes_deg']),
                                       plates=tuple(rule[prefix+'_plates']),
                                       kinds={int(i): dict(v) for i, v in rule[prefix+'_kinds'].items()})
                other = self.history(world, ridge, trench)
                self.compare(coarse, other, {ridge: 'boundary-m02', trench: 'boundary-m04'})


# ----------------------------------------------------------------------------- slow histories (round 1, S1)

THIN = T.THIN_FACE_RATIO


def c7_m2(network, index):
    bound = S._measure_bound(network.face_coordinates(index))
    return None if bound is None else bound*network.sphere.radius_m**2


def thin_terms(network):
    """{face index: its C7 bound in m2 (None where undefined)} for the thin faces of ``network``."""
    return {k: c7_m2(network, k) for k in range(len(network.face_ids)) if area_over_perimeter(network, k) < THIN}


def scoped(state, terms, select):
    """(exact column totals, aggregate C7 term per column) over the pieces ``select(plate, cohort)`` accepts.

    A thin face's term is scaled, per column, by the share of its measured area its selected pieces carry.
    """
    material, network = state.material, state.network
    width = len(material.columns)
    totals, slack = [Fraction(0)]*width, [0.]*width
    for row in range(len(material.piece_face)):
        k = int(material.piece_face[row])
        if not select(network.faces[k].plate_id, material.cohorts[int(material.piece_cohort[row])].cohort_id):
            continue
        for c, value in enumerate(material.stock[row]):
            totals[c] += Fraction(float(value))
            if k in terms:
                if terms[k] is None:
                    raise AssertionError('C7 undefined for thin face %r' % network.face_ids[k])
                slack[c] += terms[k]*abs(float(value))/float(network.face_area_m2[k])
    return totals, slack


def consumption(party):
    """A trench's account or its destination's: what the trench swept, measured in the step itself."""
    return party.startswith('trench|') or party == 'slab'


CONSUMPTION_BEYOND = ('Historical strict S1 controls: the 11 m sweep at 1e-4 degrees is not a face of either endpoint, '
                      'so their original face set gives consumed accounts no C7 term. Round 1 observed differences '
                      'up to 23.5 times that bound (2.35e-11 relative). The coordinator approved retaining these '
                      'expected failures on 3 October 2026. Fresh SweptConsumptionTests instead check actual swept '
                      'polygons under the separately predeclared S1(b) rule; no historical bound is widened.')


def born_by(party):
    """The cohorts a supplied account's party produced: a ridge side's own, every born cohort for the source, and
    none for a trench or its destination (consumed cells are compact here)."""
    if party.startswith('ridge|'):
        prefix = party[len('ridge|'):]+'|'
        return lambda plate, cohort: cohort.startswith(prefix)
    if party == 'mantle-source':
        return lambda plate, cohort: not cohort.startswith('inherited-')
    return lambda plate, cohort: False


def within(test, a, b, slack, label):
    for c, (x, y, s) in enumerate(zip(a, b, slack)):
        bound = RELATIVE*abs(float(x))+s
        test.assertLessEqual(abs(float(x)-float(y)), bound, (label, c, float(x), float(y), bound))


def slow_jump_history(rule, tilt=None):
    """equivalence_rotated_slow's history: A turns turns_deg[k] in interval k+1, interval jump_after_interval ends
    with the ridge jump, then A-east turns follow_turn_deg at the new ridge."""
    jumped = control('event_ridge_jump')
    slice_, east = tuple(jumped['split']['parts'])
    grown = jumped['merge']['new_plate']
    states = [F.crust(F.three_plates(tilt=tilt))]
    for k, turn in enumerate(rule['turns_deg']):
        motion = F.one_plate_motion(turn, step=k, tilt=tilt)
        end = (k+1)*MYR
        if k+1 == rule['jump_after_interval']:
            endpoint = T.advance(states[-1], motion, end_time_s=end).state.network
            west = tuple(sorted(f.face_id for f in endpoint.faces if f.plate_id == 'A'
                                and not f.face_id.startswith('s03-')))
            eastern = tuple(sorted(f.face_id for f in endpoint.faces if f.plate_id == 'A'
                                   and f.face_id.startswith('s03-')))
            chain = ('S',)+tuple(F.vertex(3, j) for j in range(5))+('N',)
            split = E.Split(jumped['split']['event_id'], 'A', ((slice_, west), (east, eastern)),
                            S.Boundary(jumped['split']['boundary_id'], S.RIDGE, slice_, east, chain,
                                       S.Origin(S.EVENT, jumped['split']['event_id']), accretion_fraction=.5), end)
            jump = E.RidgeJump('jump', split, E.Merge(jumped['merge']['event_id'], tuple(jumped['merge']['plates']),
                                                      grown, end))
            motion = F.one_plate_motion(turn, step=k, tilt=tilt, events=(jump,))
        states.append(T.advance(states[-1], motion, end_time_s=end).state)
    k = len(rule['turns_deg'])
    follow = T.Motion(k, k+1, {east: F.spin(rule['follow_turn_deg'], tilt), 'B': F.IDENTITY, grown: F.IDENTITY},
                      supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
    states.append(T.advance(states[-1], follow, end_time_s=(k+1)*MYR).state)
    return states


def axis_of(entry):
    name, record = entry
    return F.TILT if record == 'cases/i03_controls_v1.json#tilt' else F.rotation(record)


class RotatedSlowTests(unittest.TestCase):
    histories = {}

    @classmethod
    def history(cls, entry=None):
        key = None if entry is None else entry[0]
        if key not in cls.histories:
            rule = control('equivalence_rotated_slow')
            cls.histories[key] = slow_jump_history(rule, None if entry is None else axis_of(entry))
        return cls.histories[key]

    def terms(self, a, b):
        return {k: max(c7_m2(a.network, k), c7_m2(b.network, k)) for k in range(len(a.network.face_ids))
                if min(area_over_perimeter(a.network, k), area_over_perimeter(b.network, k)) < THIN}

    @unittest.expectedFailure
    def test_the_consumption_accounts_of_a_slow_history_in_rotated_axes(self):
        # CONSUMPTION_BEYOND: reported, not absorbed. An unexpected success is reported too.
        for entry in control('equivalence_rotated_slow')['axes']:
            for a, b in zip(self.history(), self.history(entry)):
                sa, sb = a.material.supplied(), b.material.supplied()
                for party in filter(consumption, sa):
                    for column in sorted(sa[party]):
                        within(self, [sa[party][column]], [sb[party][column]], [0.], (entry[0], party, column))

    def test_a_slow_history_in_rotated_axes_agrees_within_the_aggregate_bound(self):
        rule = control('equivalence_rotated_slow')
        plain = self.history()
        for entry in rule['axes']:
            with self.subTest(axes=entry[0]):
                other = self.history(entry)
                thin_seen = 0
                for a, b in zip(plain, other):
                    self.assertEqual(a.network.face_ids, b.network.face_ids)
                    self.assertTrue(a.material.closure()['identity_exact'] and b.material.closure()['identity_exact'])
                    terms = {}
                    for k, name in enumerate(a.network.face_ids):
                        x, y = float(a.network.face_area_m2[k]), float(b.network.face_area_m2[k])
                        if min(area_over_perimeter(a.network, k), area_over_perimeter(b.network, k)) < THIN:
                            ea, eb = c7_m2(a.network, k), c7_m2(b.network, k)
                            self.assertIsNotNone(ea, name)
                            self.assertIsNotNone(eb, name)
                            terms[k] = max(ea, eb)
                            self.assertLessEqual(abs(x-y), terms[k], name)
                            thin_seen += 1
                        else:
                            close(self, y, x, name)
                    for scope, select, names in (
                            ('plate', lambda key: (lambda plate, cohort: plate == key), a.network.plate_ids),
                            ('cohort', lambda key: (lambda plate, cohort: cohort == key),
                             [c.cohort_id for c in a.material.cohorts])):
                        for key in names:
                            ta, slack = scoped(a, terms, select(key))
                            tb, _ = scoped(b, terms, select(key))
                            within(self, ta, tb, slack, (scope, key))
                    sa, sb = a.material.supplied(), b.material.supplied()
                    self.assertEqual(sorted(sa), sorted(sb))
                    for party in sa:
                        if consumption(party):
                            continue                     # their own (expected-failure) test
                        columns = sorted(sa[party])
                        _, slack = scoped(a, terms, born_by(party))
                        area = slack[a.material.columns.index('area_m2')] if 'area_m2' in columns else 0.
                        for column in columns:
                            share = slack[a.material.columns.index(column)] if column in a.material.columns else area
                            within(self, [sa[party][column]], [sb[party][column]], [share], (party, column))
                self.assertGreater(thin_seen, 0, 'the slow history must hold thin faces')


MESHES = (('refined', 'boundary-m04', 'boundary-m08'), ('non_nested', 'boundary-m03', 'boundary-m06'))


class MeshSlowTests(unittest.TestCase):
    histories = {}

    @classmethod
    def history(cls, prefix=None):
        if prefix not in cls.histories:
            rule, fast = control('equivalence_meshes_slow'), control('equivalence_meshes')
            mesh = MeshTests()
            if prefix is None:
                cls.histories[prefix] = mesh.history(F.three_plates(), 'boundary-m02', 'boundary-m04', rule,
                                                     compact=False)
            else:
                ridge, trench = [(r, t) for p, r, t in MESHES if p == prefix][0]
                world = F.three_plates(longitudes_deg=tuple(fast[prefix+'_longitudes_deg']),
                                       latitudes_deg=tuple(fast[prefix+'_latitudes_deg']),
                                       plates=tuple(fast[prefix+'_plates']),
                                       kinds={int(i): dict(v) for i, v in fast[prefix+'_kinds'].items()})
                cls.histories[prefix] = mesh.history(world, ridge, trench, rule, compact=False)
        return cls.histories[prefix]

    @unittest.expectedFailure
    def test_the_consumption_accounts_of_a_slow_history_on_other_meshes(self):
        # CONSUMPTION_BEYOND: reported, not absorbed. An unexpected success is reported too.
        coarse = self.history()
        for prefix, ridge, trench in MESHES:
            names = {ridge: 'boundary-m02', trench: 'boundary-m04'}
            role = lambda name: '|'.join(names.get(token, token) for token in name.split('|'))
            sa = coarse.material.supplied()
            sb = {role(name): values for name, values in self.history(prefix).material.supplied().items()}
            for party in filter(consumption, sa):
                for column in sorted(sa[party]):
                    within(self, [sa[party][column]], [sb[party][column]], [0.], (prefix, party, column))

    def test_a_slow_history_on_other_meshes_agrees_within_the_aggregate_bound(self):
        rule = control('equivalence_meshes_slow')
        coarse = self.history()
        terms_c = thin_terms(coarse.network)
        self.assertTrue(terms_c, 'the slow history must hold thin faces')
        for prefix, ridge, trench in MESHES:
            with self.subTest(mesh=prefix):
                other = self.history(prefix)
                terms_o = thin_terms(other.network)
                names = {ridge: 'boundary-m02', trench: 'boundary-m04'}
                role = lambda name: '|'.join(names.get(token, token) for token in name.split('|'))
                everything = lambda plate, cohort: True
                for scope, select_c, select_o in (
                        [('global', everything, everything)]
                        + [(('plate', p), (lambda key: lambda plate, cohort: plate == key)(p),
                            (lambda key: lambda plate, cohort: plate == key)(p)) for p in coarse.network.plate_ids]
                        + [(('cohort', c.cohort_id), (lambda key: lambda plate, cohort: cohort == key)(c.cohort_id),
                            (lambda key: lambda plate, cohort: role(cohort) == key)(c.cohort_id))
                           for c in coarse.material.cohorts]):
                    tc, sc = scoped(coarse, terms_c, select_c)
                    to, so = scoped(other, terms_o, select_o)
                    within(self, tc, to, [max(x, y) for x, y in zip(sc, so)], scope)
                sa = coarse.material.supplied()
                sb = {role(name): values for name, values in other.material.supplied().items()}
                self.assertEqual(sorted(sa), sorted(sb))
                for party in sa:
                    if consumption(party):
                        continue                         # their own (expected-failure) test
                    _, sc = scoped(coarse, terms_c, born_by(party))
                    _, so = scoped(other, terms_o, (lambda chosen: lambda plate, cohort: chosen(plate, role(cohort)))(
                        born_by(party)))
                    columns = coarse.material.columns
                    area = max(sc[columns.index('area_m2')], so[columns.index('area_m2')])
                    for column in sorted(sa[party]):
                        share = max(sc[columns.index(column)], so[columns.index(column)]) if column in columns else area
                        within(self, [sa[party][column]], [sb[party][column]], [share], (party, column))
                born = F.lune(rule['turn_deg']/2*rule['intervals'])
                for side in ('left', 'right'):
                    _, so = scoped(other, terms_o,
                                   (lambda s: lambda plate, cohort: role(cohort).startswith('boundary-m02|'+s+'|'))(side))
                    within(self, [born], [sb['ridge|boundary-m02|'+side]['area_m2']],
                           [so[other.material.columns.index('area_m2')]], ('lune', side))


class SweptConsumptionTests(unittest.TestCase):
    """Fresh S1(b) control, declared in consumption_sweep_c7_repair before this test first ran.

    Historical controls above retain their strict criteria and expected failures. These comparisons add only the
    existing C7 bound of the actual sweep polygons, propagated by the consumed material's areal densities.
    """
    measured_bound_fractions = {}

    def history(self, network, ridge='boundary-m02', trench='boundary-m04', tilt=None):
        rule = control('consumption_sweep_c7_repair')
        state, bounds = F.crust(network), {}
        for k in range(rule['intervals']):
            original = T._consumption_accuracy

            def thin_sweeps(parent, material, moved, rows, supplies):
                self.assertTrue(moved.swept, 'S1(b) requires actual sweep polygons')
                for boundary, _, ring in moved.swept:
                    perimeter = math.fsum(float(T._angle(a, b))
                                          for a, b in zip(ring, np.roll(ring, -1, axis=0)))
                    self.assertGreater(perimeter, 0., boundary)
                    self.assertLess(T._exact_ring_sr(ring)/perimeter, T.THIN_FACE_RATIO, boundary)
                return original(parent, material, moved, rows, supplies)

            with mock.patch.object(T, '_consumption_accuracy', thin_sweeps):
                step = T.advance(state,
                                 F.one_plate_motion(rule['turn_deg'], step=k, ridge=ridge, trench=trench, tilt=tilt),
                                 end_time_s=(k+1)*MYR)
            MeshTests().assert_single_cohort_consumption(state, step, trench)
            diagnostic = step.summary()['consumption_accuracy'][trench]
            self.assertIsNotNone(diagnostic['sweep_c7_m2'])
            for column, value in diagnostic['account_roundoff'].items():
                self.assertIsNotNone(value)
                bounds[column] = bounds.get(column, 0.)+value
            state = step.state
        consumed = state.material.supplied()
        totals = {column: -consumed['trench|'+trench]['area_m2'] if column == 'area_m2' else -consumed['slab'][column]
                  for column in state.material.columns}
        return totals, bounds

    def compare(self, label, first, second):
        a, ba = first
        b, bb = second
        fractions = []
        for column in a:
            slack = max(ba[column], bb[column])
            bound = RELATIVE*abs(float(a[column]))+slack
            difference = abs(float(a[column])-float(b[column]))
            fractions.append(difference/bound)
            within(self, [a[column]], [b[column]], [slack], (label, column))
            # A real positive discrepancy outside the predeclared bound is still rejected; no expectedFailure mask.
            with self.assertRaises(AssertionError):
                within(self, [a[column]], [float(a[column])+2*bound], [slack], (label, 'beyond', column))
        self.measured_bound_fractions[label] = max(fractions)

    def test_slow_consumption_across_axes_and_meshes_uses_actual_sweep_bounds(self):
        plain = self.history(F.three_plates())
        for entry in control('equivalence_rotated_slow')['axes']:
            tilt = axis_of(entry)
            self.compare(entry[0], plain, self.history(F.three_plates(tilt=tilt), tilt=tilt))
        fast = control('equivalence_meshes')
        for prefix, ridge, trench in MESHES:
            world = F.three_plates(longitudes_deg=tuple(fast[prefix+'_longitudes_deg']),
                                   latitudes_deg=tuple(fast[prefix+'_latitudes_deg']),
                                   plates=tuple(fast[prefix+'_plates']),
                                   kinds={int(i): dict(v) for i, v in fast[prefix+'_kinds'].items()})
            self.compare(prefix, plain, self.history(world, ridge, trench))


if __name__ == '__main__':
    unittest.main()
