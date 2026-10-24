"""I05.1 transport of complete material records (tectonics/docs/I05_MOVING_STATE.md).

Bond-record parity: the package reproduction equals tools/check_i01_separation_feasibility.py (R-5, no tool moved).
The tool is imported here only; production code never imports it.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
from fractions import Fraction
import itertools
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_i01_separation_feasibility as separation       # noqa: E402
import i03_fixtures as F                                    # noqa: E402
import i05_fixtures as X                                    # noqa: E402

from atlas_tectonics import integration_material as M      # noqa: E402
from atlas_tectonics import integration_sphere as S        # noqa: E402
from atlas_tectonics import integration_splits as P        # noqa: E402
from atlas_tectonics import integration_transfer as T      # noqa: E402


def outcome(function, *args, **kwargs):
    try:
        return 'ok', function(*args, **kwargs)
    except (separation.Refusal, M.BondRefused) as exc:
        return 'refused', exc.code


def fields(record):
    return (record.cohort, record.ever_broken, record.support, record.bond)


class BondParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.law = separation.SofteningLaw(**separation.load_case()['law'])

    def test_observe_matches_the_tool_on_every_support_and_latch(self):
        (t_low, t_high), (p_low, p_high) = self.law.support_temperature_k, self.law.support_effective_pressure_pa
        histories = (0, self.law.softening_history/2, self.law.softening_history, 2*self.law.softening_history)
        states = (t_low, (t_low+t_high)/2, t_high*1.01)
        pressures = (p_low, (p_low+p_high)/2, p_high*1.01+1)
        laws = (self.law, replace(self.law, residual_state='weakened_intact'))
        checked = set()
        for law, latch, support, segment, history, t, p in itertools.product(
                laws, (False, True), M.SUPPORTS, M.SUPPORTS, histories, states, pressures):
            ours = M.BondRecord('rock-A', latch, support).observe(law, history, t, p, increment_support=segment)
            theirs = separation.BondHistory('rock-A', latch, support).observe(law, history, t, p,
                                                                              increment_support=segment)
            self.assertEqual(fields(ours), fields(theirs))
            self.assertTrue(ours.ever_broken or not latch)       # never cleared
            checked.add(ours.bond)
        self.assertEqual(checked, set(M.BONDS))

    def test_refusals_match(self):
        for args in (('', False, 'INSIDE'), ('rock', 0, 'INSIDE'), ('rock', False, 'inside'), (3, False, 'INSIDE')):
            self.assertEqual(outcome(M.BondRecord, *args), ('refused', M.INVALID_INPUT))
            self.assertEqual(outcome(separation.BondHistory, *args), ('refused', M.INVALID_INPUT))
        record, theirs = M.BondRecord('rock', False, 'INSIDE'), separation.BondHistory('rock', False, 'INSIDE')
        for history, t, p, segment in ((-1, 300, 1, 'INSIDE'), (1, 0, 1, 'INSIDE'), (1, 300, -1, 'INSIDE'),
                                       (math.nan, 300, 1, 'INSIDE'), (1, 300, 1, 'maybe'), (True, 300, 1, 'INSIDE')):
            self.assertEqual(outcome(record.observe, self.law, history, t, p, increment_support=segment),
                             outcome(theirs.observe, self.law, history, t, p, increment_support=segment))

    def test_distinct_records_are_preserved_never_averaged(self):
        ours = (M.BondRecord('A', False, 'INSIDE'), M.BondRecord('B', True, 'INSIDE'))
        self.assertEqual(M.preserve_bond_records(ours), ours)
        self.assertEqual(outcome(M.preserve_bond_records, ()), ('refused', M.INVALID_INPUT))
        self.assertEqual(outcome(M.preserve_bond_records, ours+(M.BondRecord('A', True, 'UNKNOWN'),)),
                         ('refused', M.INVALID_INPUT))
        self.assertEqual(outcome(M.preserve_bond_records, (separation.BondHistory('A', False, 'INSIDE'),)),
                         ('refused', M.INVALID_INPUT))


def merged_face(sector=0, plate='C'):
    """One face covering bands 1 and 2 of a sector: the I03 mesh-change control's merge."""
    k = sector+1
    return S.Face('s%02d-merged' % sector, plate, (F.vertex(sector, 1), F.vertex(k, 1), F.vertex(k, 2),
                                                    F.vertex(k, 3), F.vertex(sector, 3), F.vertex(sector, 2)))


def remesh(state, remove, add, step=0, **changes):
    faces = {face.face_id: face for face in state.network.faces}
    for name in remove:
        del faces[name]
    for face in add:
        faces[face.face_id] = face
    values = dict(start_step=step, end_step=step+1, rotations={p: F.IDENTITY for p in state.network.plate_ids},
                  mesh=T.Mesh(tuple(faces.values())))
    values.update(changes)
    return T.Motion(**values)


def refused(test, code, function, *args, **kwargs):
    with test.assertRaises(M.TransportRefused) as caught:
        function(*args, **kwargs)
    test.assertEqual(caught.exception.code, code, str(caught.exception))
    return caught.exception


class MovingTransport(unittest.TestCase):
    """I05.1: complete records move with the I03 rows; nothing is invented, averaged, reset or lost."""

    @classmethod
    def setUpClass(cls):
        cls.network = F.three_plates()
        cls.state = X.crust(cls.network)
        cls.moving = X.moving(cls.state)

    def advanced(self, motion=None, advance=None, state=None, moving=None):
        state = self.state if state is None else state
        moving = self.moving if moving is None else moving
        step = X.stepped(state, X.motion() if motion is None else motion)
        return step, M.advance_moving(moving, state, step, X.advance() if advance is None else advance)

    def test_rigid_rotation_and_stationary_cases_change_nothing(self):
        for rotation in (F.IDENTITY, F.spin(5.)):
            motion = T.Motion(0, 1, {p: rotation for p in 'ABC'})
            step, out = self.advanced(motion, M.MovingAdvance(0, 1))
            self.assertEqual((step.map.rows, step.map.mesh_rows), ((), ()))
            after = out.state
            self.assertEqual(after.cohorts, self.moving.cohorts)               # no history, date or profile reset
            self.assertEqual(after.pieces, self.moving.pieces)
            self.assertEqual(after.arrays()['moving.heat_j'].tobytes(), self.moving.arrays()['moving.heat_j'].tobytes())
            self.assertEqual(after.supplied(), {})
            self.assertTrue(after.closure()['identity_exact'])
            self.assertEqual(after.state_id, step.state.state_id)

    def test_moving_pulse_births_and_consumption_close_exactly(self):
        """Plate A, heated, rides between a ridge and a trench: its riding pieces keep their bytes, born crust
        takes its birth column's heat, consumed heat leaves to the trench's destination, and the accounts close."""
        records = (X.record('inherited-A', top=900., bottom=1100.), X.record('inherited-B'), X.record('inherited-C'))
        moving = M.declare_moving(self.state, records, enthalpy_reference_k=X.T_REF)
        step, out = self.advanced(moving=moving)
        after = out.state
        self.assertTrue(after.closure()['identity_exact'])
        supplied = after.supplied()
        born = {key: value for key, value in supplied.items() if key.startswith('ridge|')}
        self.assertEqual(sorted(born), ['ridge|boundary-m02|left', 'ridge|boundary-m02|right'])
        self.assertLess(supplied['slab'], 0)                                 # consumed heat left through the trench
        # A born piece holds exactly its birth column's declared heat per area times its area, rounded once.
        column = X.birth_column()
        for i, (face, cohort) in enumerate(after.pieces):
            if cohort.startswith('boundary-m02|'):
                area = step.state.material.pieces()[i].area_m2
                expected = [float(Fraction(s.declared_heat_per_area(X.T_REF))*Fraction(area)) for s in column.sublayers]
                self.assertEqual(after.heat_j(i).tolist(), expected)
                self.assertEqual(after.cohort(cohort).kappa, (0.,)*X.LAYERS)
        # A piece that only rode keeps its bytes; its record is unchanged.
        riding = [key for key in after.pieces if key in moving.pieces and key[1] == 'inherited-C']
        self.assertTrue(riding)
        for key in riding:
            self.assertEqual(after.heat_j(after.pieces.index(key)).tobytes(),
                             moving.heat_j(moving.pieces.index(key)).tobytes())
        self.assertEqual(after.cohort('inherited-A'), moving.cohort('inherited-A'))
        # Exact balance belongs to positioned patch heat. The rounded piece
        # projection has its own exact residual, not physical heat or a tolerance.
        total = sum((value for _, column in after._patch_heat for value in column), Fraction(0))
        self.assertEqual(total, after._initial+sum(after._supplied and [v for _, v in after._supplied], Fraction(0))
                         + after._rounding)
        projected = sum((Fraction(float(x)) for i in range(len(after.pieces)) for x in after.heat_j(i)), Fraction(0))
        self.assertEqual(projected-total, after._projection_rounding)

    def test_mixed_bonded_and_broken_cohorts_stay_distinct_in_one_cell(self):
        cohort_of = {'s00-b01': 'bonded-C', 's00-b02': 'broken-C'}
        state = X.crust(self.network, cohort_of=lambda f: cohort_of.get(f, 'inherited-'+self.network.face_plate(f)))
        records = tuple(X.record(c.cohort_id, bond=('INSIDE', c.cohort_id == 'broken-C'))
                        for c in state.material.cohorts)
        moving = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF)
        step = X.stepped(state, remesh(state, ('s00-b01', 's00-b02'), (merged_face(),)))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state
        held = [cohort for face, cohort in out.pieces if face == 's00-merged']
        self.assertEqual(held, ['bonded-C', 'broken-C'])                    # two pieces, never one averaged one
        bonds = {cohort: out.cohort(cohort).bond for cohort in held}
        self.assertEqual({c: (b.ever_broken, b.bond) for c, b in bonds.items()},
                         {'bonded-C': (False, 'BONDED'), 'broken-C': (True, 'BROKEN')})
        self.assertEqual(M.preserve_bond_records(tuple(bonds.values())), tuple(bonds.values()))
        # Each cohort's heat moved whole into the merged face; the cell holds the sum of nothing.
        for cohort, face in (('bonded-C', 's00-b01'), ('broken-C', 's00-b02')):
            self.assertEqual(out.heat_j(out.pieces.index(('s00-merged', cohort))).tobytes(),
                             moving.heat_j(moving.pieces.index((face, cohort))).tobytes())

    def test_ever_broken_survives_remap_and_cannot_be_cleared(self):
        records = tuple(X.record(c.cohort_id, bond=('INSIDE', c.cohort_id == 'inherited-C'))
                        for c in self.state.material.cohorts)
        moving = M.declare_moving(self.state, records, enthalpy_reference_k=X.T_REF)
        step = X.stepped(self.state, remesh(self.state, ('s00-b01', 's00-b02'), (merged_face(),)))
        after = M.advance_moving(moving, self.state, step, M.MovingAdvance(0, 1)).state
        bond = after.cohort('inherited-C').bond
        self.assertTrue(bond.ever_broken)
        law = separation.SofteningLaw(**separation.load_case()['law'])
        (t_low, _), (p_low, _) = law.support_temperature_k, law.support_effective_pressure_pa
        self.assertTrue(bond.observe(law, 0., t_low, p_low, increment_support='INSIDE').ever_broken)

    def test_memories_and_the_original_profile_survive_a_move(self):
        compaction = M.CompactionMemory('test:drained-law', 'test:conditions', (('p1', 0.8, 2.e6), ('p2', 0.5, 9.e6)))
        records = tuple(replace(X.record(c.cohort_id), compaction=compaction) if c.cohort_id == 'inherited-A'
                        else X.record(c.cohort_id) for c in self.state.material.cohorts)
        moving = M.declare_moving(self.state, records, enthalpy_reference_k=X.T_REF)
        step, out = self.advanced(moving=moving)
        later = M.advance_moving(out.state, step.state, X.stepped(step.state, X.motion(step=1)), X.advance(1)).state
        for cohort in ('inherited-A', 'inherited-B', 'inherited-C'):
            self.assertEqual(later.cohort(cohort), moving.cohort(cohort))
        self.assertEqual(later.cohort('inherited-A').compaction, compaction)
        self.assertEqual(later.cohort('inherited-B').elastic, M.NOT_REPRESENTED)
        with self.assertRaises(M.TransportRefused):
            replace(X.record('x'), elastic=None)                              # never absent or zero
        with self.assertRaises(M.TransportRefused):                           # the I01 bounds are not clipped
            M.ElasticMemory(3e7, 0., 0., 1e9, 0., 'frame', 'map_view', 'test:modulus', 'INSIDE')

    def test_raw_history_is_untouched_by_transport_and_incremented_once_per_cohort(self):
        step, out = self.advanced()
        for c in self.moving.cohorts:
            self.assertEqual(out.state.cohort(c.cohort_id).kappa, c.kappa)
        pieces = out.state.pieces
        uniform = tuple(((face, cohort), (0.01,)*X.LAYERS) for face, cohort in pieces if cohort == 'inherited-A')
        later = M.advance_moving(self.moving, self.state, step, X.advance(increments=uniform)).state
        self.assertEqual(later.cohort('inherited-A').kappa, (0.01,)*X.LAYERS)
        self.assertEqual(later.cohort('inherited-B').kappa, (0.,)*X.LAYERS)
        varied = tuple((key, (0.01*(1+i % 2),)*X.LAYERS) for i, (key, _) in enumerate(uniform))
        error = refused(self, M.DIVERGENCE, M.advance_moving, self.moving, self.state, step,
                        X.advance(increments=varied))
        self.assertEqual(error.detail, 'inherited-A')
        refused(self, M.MISSING, M.advance_moving, self.moving, self.state, step, X.advance(increments=varied[:1]))
        refused(self, M.UNSUPPORTED, X.advance, increments=((varied[0][0], (-1.,)*X.LAYERS),))

    def test_divergent_increments_split_the_cohort_and_commit_once_each(self):
        """The two-pass P6 flow: advance, take per-piece increments, split, advance again, commit."""
        first = X.stepped(self.state, X.motion())
        held = [key for key in first.state.material.pieces() if key.cohort_id == 'inherited-A']
        increments = {(p.face_id, p.cohort_id): (0.01*(1+i % 3),)*X.LAYERS for i, p in enumerate(held)}
        splits, renamed = M.split_for_increments(first, increments,
                                                 history_of=lambda cohort, value: 'test:kappa-%s-%r' % (cohort,
                                                                                                        value[0]))
        self.assertEqual(len(splits), 1)
        self.assertEqual(len(splits[0].groups), 2)                            # three values: one stays, two split
        step = X.stepped(self.state, X.motion(history_splits=splits))
        out = M.advance_moving(self.moving, self.state, step, X.advance(increments=renamed)).state
        kappas = {c.cohort_id: c.kappa[0] for c in out.cohorts if 'inherited-A' == c.cohort_id
                  or c.cohort_id.startswith(P.PREFIX)}
        self.assertEqual(sorted(kappas.values()), [0.01, 0.02, 0.03])
        self.assertTrue(out.closure()['identity_exact'])
        for cohort in kappas:                                                  # one history per cohort
            values = {v for (face, c), v in renamed if c == cohort}
            self.assertEqual(len(values), 1)
        children = [c for c in out.cohorts if c.cohort_id.startswith(P.PREFIX)]
        self.assertTrue(all(c.sublayers == self.moving.cohort('inherited-A').sublayers for c in children))
        # splits-5: pass 2 is pass 1 apart from the relabel. Every array but the cohort records, the piece cohorts and
        # the lineage is byte-identical (rows, mesh rows, stock, faces, transfers), and each piece is pass 1's piece
        # under its split name.
        first_arrays, second_arrays = first.arrays(), step.arrays()
        differ = {name for name in set(first_arrays) | set(second_arrays)
                  if name not in first_arrays or name not in second_arrays
                  or np.asarray(first_arrays[name]).tobytes() != np.asarray(second_arrays[name]).tobytes()}
        self.assertEqual(differ, {'sphere.cohorts', 'sphere.piece_cohort', 'sphere.split_parent',
                                  'sphere.split_child', 'sphere.material_support'})
        relabel = {}
        for split in splits:
            for history, faces in split.groups:
                for face in faces:
                    relabel[(face, split.cohort_id)] = P.sub_cohort_id(split.cohort_id, 1, history)
        moved = [(p.face_id, relabel.get((p.face_id, p.cohort_id), p.cohort_id), p.area_m2, p.mass_kg, p.volume_m3)
                 for p in first.state.material.pieces()]
        again = [(p.face_id, p.cohort_id, p.area_m2, p.mass_kg, p.volume_m3) for p in step.state.material.pieces()]
        self.assertEqual(sorted(moved), sorted(again))
        self.assertEqual(first.summary()['births'], step.summary()['births'])

    def test_refusals(self):
        step = X.stepped(self.state, X.motion())
        refused(self, M.MISSING, M.advance_moving, self.moving, self.state, step, M.MovingAdvance(0, 1))  # no birth
        refused(self, M.STALE, M.advance_moving, self.moving, self.state, step, X.advance(1))
        later = X.stepped(step.state, X.motion(step=1))
        refused(self, M.STALE, M.advance_moving, self.moving, self.state, later, X.advance(1))
        other = X.crust(F.three_plates(), cohort_of=lambda f: 'other')
        refused(self, M.STALE, M.advance_moving, self.moving, other, step, X.advance())
        wrong = M.BirthColumn('test:thin', X.SOURCE, X.sublayers(layers=2)[:1], X.T_SURFACE, X.T_BASE)
        refused(self, M.INCOMPATIBLE, M.advance_moving, self.moving, self.state, step,
                M.MovingAdvance(0, 1, births=((X.BIRTH_HISTORY, wrong),)))
        refused(self, M.INCOMPATIBLE, M.declare_moving, F.crust(self.network), tuple(
            X.record(c.cohort_id) for c in self.state.material.cohorts), enthalpy_reference_k=X.T_REF)
        refused(self, M.MISSING, M.declare_moving, self.state, (X.record('inherited-A'),),
                enthalpy_reference_k=X.T_REF)
        refused(self, M.MISSING, M.declare_moving, self.state, tuple(
            X.record(c.cohort_id) for c in self.state.material.cohorts), enthalpy_reference_k=None)

    def test_identical_replay_is_idempotent_and_a_stale_replay_refuses(self):
        step, out = self.advanced()
        again = M.advance_moving(self.moving, self.state, step, X.advance())
        self.assertEqual(again.state.moving_id, out.state.moving_id)
        stored = M.restore_moving(out.state.descriptor(), out.state.arrays(), step.state)
        self.assertEqual(stored.moving_id, out.state.moving_id)
        edited = dict(out.state.arrays())
        edited['moving.heat_j'] = edited['moving.heat_j'].copy()
        edited['moving.heat_j'][0] *= 1+1e-9                              # an edit binary64 can hold
        with self.assertRaises(M.TransportRefused):
            M.restore_moving(out.state.descriptor(), edited, step.state)
        # Stored bytes are compared exactly and no other moving array is admitted (as restore_sphere's exclusive
        # root check): a trailing value, an edited offset or an extra array is refused, not sliced away.
        arrays = out.state.arrays()
        offsets = arrays['moving.heat_offsets'].copy()
        offsets[-1] += 100
        start = arrays['moving.heat_offsets'].copy()
        start[0] = -len(arrays['moving.heat_j'])
        for change in (dict(arrays, **{'moving.heat_j': np.append(arrays['moving.heat_j'], 1.)}),
                       dict(arrays, **{'moving.heat_offsets': offsets}),
                       dict(arrays, **{'moving.heat_offsets': start}),
                       dict(arrays, **{'moving.zzz': np.zeros(1)})):
            refused(self, M.STALE, M.restore_moving, out.state.descriptor(), change, step.state)
        refused(self, M.STALE, M.advance_moving, out.state, step.state, step, X.advance())


class AdvanceDeclarations(unittest.TestCase):
    """A MovingAdvance owns its content from construction; malformed or unused content refuses with its code."""

    @classmethod
    def setUpClass(cls):
        cls.network = F.three_plates()
        cls.state = X.crust(cls.network)
        cls.moving = X.moving(cls.state)

    def test_a_later_edit_of_the_callers_certificate_cannot_reach_the_advance(self):
        certificate = X.certificate(X.MYR)
        advance = M.MovingAdvance(0, 1, conduction=M.Conduction('omit', certificate=certificate))
        record = advance.record()
        certificate['windows'][0]['envelope']['basis'] = 'edited after construction'
        certificate['temperature_allowance_k'] = 10**9
        self.assertEqual(advance.record(), record)
        self.assertEqual(M.MovingAdvance.from_record(record).advance_id, advance.advance_id)
        given = advance.conduction.declared_certificate()
        given['temperature_allowance_k'] = 10**9                    # a copy: the advance is unchanged
        self.assertEqual(advance.record(), record)

    def test_malformed_content_refuses_with_its_code(self):
        for value in (Fraction(1), math.nan, math.inf):
            certificate = dict(X.certificate(X.MYR), temperature_allowance_k=value)
            error = refused(self, M.MISSING, M.Conduction, 'omit', certificate=certificate)
            self.assertEqual(error.detail, 'certificate')
        piece = ('s00-b00', 'inherited-A')
        for increments in (((('s00-b00',), (0.,)),), (('ab', (0.,)),), ((piece, 0.),), ((piece, ('x',)),),
                           ((piece, (math.nan,)),), ((piece,),), (piece,)):
            with self.subTest(increments=increments):
                refused(self, M.MISSING, M.MovingAdvance, 0, 1, increments=increments)
        for row in (dict(M.MovingAdvance(0, 1).record(), increments=[['x', [0.]]]),
                    dict(M.MovingAdvance(0, 1).record(), increments=[[['a'], [0.]]])):
            refused(self, M.MISSING, M.MovingAdvance.from_record, row)

    def test_minus_zero_increments_are_zero(self):
        held = [p for p in self.state.material.pieces() if p.cohort_id == 'inherited-A']
        given = {(p.face_id, p.cohort_id): ((-0.0 if i % 2 else 0.0),)*X.LAYERS for i, p in enumerate(held)}
        advance = M.MovingAdvance(0, 1, increments=tuple(given.items()))
        self.assertTrue(all(math.copysign(1., v) == 1. for _, values in advance.increments for v in values))
        step = X.stepped(self.state, T.Motion(0, 1, {p: F.IDENTITY for p in 'ABC'}))
        splits, _ = M.split_for_increments(step, given, history_of=lambda c, v: 'test:%s' % c)
        self.assertEqual(splits, ())                       # one value, so no split and no divergence

    def test_an_unused_birth_column_refuses(self):
        motion = T.Motion(0, 1, {p: F.IDENTITY for p in 'ABC'})
        step = X.stepped(self.state, motion)
        error = refused(self, M.INCOMPATIBLE, M.advance_moving, self.moving, self.state, step, X.advance())
        self.assertEqual(error.detail, 'births')

    def test_a_malformed_increment_refuses_missing_before_divergence(self):
        step = X.stepped(self.state, T.Motion(0, 1, {p: F.IDENTITY for p in 'ABC'}))
        held = [p for p in step.state.material.pieces() if p.cohort_id == 'inherited-A']
        given = tuple(((p.face_id, p.cohort_id), (0.01*(1+i % 2),)) for i, p in enumerate(held))
        refused(self, M.MISSING, M.advance_moving, self.moving, self.state, step, M.MovingAdvance(0, 1,
                                                                                                  increments=given))


if __name__ == '__main__':
    unittest.main()
