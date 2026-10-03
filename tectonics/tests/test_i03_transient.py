"""D5: geometry-derived material born and consumed inside an accepted interval.

Uses supplied, coaxial kinematics on a closed V-shaped ridge/trench network and
the retained finite_stock material declarations. Every accounting control goes
through advance or the real I02 clock; no test substitutes invented transient
rows for a junction construction.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import dataclasses
import json
import math
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import i02_workflow_fixtures as F2
import i03_fixtures as F
from atlas_tectonics import integration_clock as K, integration_ledger as L
from atlas_tectonics import integration_sphere as S, integration_transfer as T

STOCK = F.control('finite_stock')
CONTROL = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']['transient']
MYR = F.MYR_S
TRENCHES = ('trench-s1', 'trench-s2-e', 'trench-s2-w')
RIDGE_SIDES = (('ridge', 'left'), ('ridge', 'right'), ('ridge-os2', 'right'))


def world(*, ledger=False):
    """A small S1 wedge, not an antipodal hemisphere with an invalid far end.

    O owns the north; S2 owns the south except the S1 triangle whose V-shaped
    ridge goes (0,0) -> (45,-30) -> (90,0). The supplied rotations move both old
    ridge ends north across the trench, with X inside both old end segments.
    The outer O/S2 ridge/trench transitions are rotation poles, so stay fixed.
    """
    vertices, rings = F.sector_mesh(CONTROL['longitudes_deg'], CONTROL['latitudes_deg'])

    def owner(name):
        south = name.endswith('south') or ('-b' in name and int(name[-2:]) < 2)
        return 'S2' if south else 'O'

    faces = [S.Face(name, owner(name), ring) for name, ring in rings.items()
             if name not in ('s00-b01', 's01-b01')]
    v = F.vertex
    faces.extend((S.Face('s00-b01-n', 'S1', (v(0, 2), v(1, 1), v(1, 2))),
                  S.Face('s00-b01-s', 'S2', (v(0, 1), v(1, 1), v(0, 2))),
                  S.Face('s01-b01-n', 'S1', (v(1, 1), v(2, 2), v(1, 2))),
                  S.Face('s01-b01-s', 'S2', (v(1, 1), v(2, 1), v(2, 2)))))

    def equator(a, b):
        return tuple(v(i % 8, 2) for i in range(a, b+1))

    boundaries = (
        S.Boundary('trench-s1', S.TRENCH, 'O', 'S1', equator(0, 2), F.origin(), subducting_side='right'),
        S.Boundary('trench-s2-e', S.TRENCH, 'O', 'S2', equator(2, 3), F.origin(), subducting_side='right'),
        S.Boundary('ridge-os2', S.RIDGE, 'O', 'S2', equator(3, 7), F.origin(), accretion_fraction=0.),
        S.Boundary('trench-s2-w', S.TRENCH, 'O', 'S2', equator(7, 8), F.origin(), subducting_side='right'),
        S.Boundary('ridge', S.RIDGE, 'S1', 'S2', (v(0, 2), v(1, 1), v(2, 2)),
                   F.origin(), accretion_fraction=.5),
    )
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=tuple(faces),
                           plates=tuple(S.Plate(p, F.IDENTITY) for p in ('O', 'S1', 'S2')),
                           boundaries=boundaries, epoch_id=F2.EPOCH if ledger else F.EPOCH,
                           time_s=F2.START if ledger else F.START)


def ridge_supplies(**changes):
    return tuple(F.supply(ridge, side, **changes) for ridge, side in RIDGE_SIDES)


def motion(**changes):
    values = dict(start_step=0, end_step=1,
                  rotations={'O': F.IDENTITY,
                             'S1': F.Rotation.from_axis_angle(CONTROL['rotation_axis'], math.radians(CONTROL['rotation_deg'][0])),
                             'S2': F.Rotation.from_axis_angle(CONTROL['rotation_axis'], math.radians(CONTROL['rotation_deg'][1]))},
                  supplies=ridge_supplies(), sinks=tuple(F.sink(name) for name in TRENCHES))
    values.update(changes)
    return T.Motion(**values)


def transient_births(step):
    return [record for record in step.record()['births'] if record.get('transient_consumption')]


class TransientTests(unittest.TestCase):
    def test_measured_triangles_have_two_account_legs_and_no_endpoint_face(self):
        state, proposed = F.crust(world()), motion()
        geometry = T._moved(state.network, proposed, None)
        self.assertEqual(len(geometry.transient), 4)
        step = T.advance(state, proposed, end_time_s=MYR)
        rows = step.map._motion
        self.assertEqual(len(rows.transient), 3)
        areas = {}
        for junction, ridge, side, trench, plate, ring in geometry.transient:
            self.assertEqual(len(ring), 3, junction)
            self.assertEqual(plate, 'S1' if side == 'left' else 'S2')
            key = ('ridge|%s|%s' % (ridge, side), 'trench|'+trench)
            areas.setdefault(key, []).append(T._ring_m2(ring, state.network.sphere))
        measured = {(rows.parties[source], rows.parties[sink]): value for source, sink, value in rows.transient}
        self.assertEqual(measured, {key: math.fsum(values) for key, values in areas.items()})
        self.assertTrue(all(value > 0 for value in measured.values()))
        records = transient_births(step)
        self.assertGreater(len(records), 0)
        cohorts = {cohort.cohort_id: cohort for cohort in step.state.material.cohorts}
        for record in records:
            cohort = cohorts[record['cohort_id']]
            self.assertEqual((cohort.formation_start_s, cohort.formation_end_s), (state.network.time_s, MYR))
            supply = next(s for s in proposed.supplies if (s.boundary_id, s.side) ==
                          (record['boundary_id'], record['side']))
            self.assertEqual((cohort.material_id, cohort.origin_id, cohort.history_id),
                             (supply.material_id, supply.origin_id, supply.history_id))
            temporary = sum((Fraction(row['area_m2']) for row in record['transient_consumption']), Fraction(0))
            surviving = sum((Fraction(rows.area_m2[k]) for k, donor in enumerate(rows.donor)
                             if donor == -1 and rows.parties[rows.party[k]] == record['party']), Fraction(0))
            self.assertEqual(Fraction(record['area_m2']), surviving+temporary)
            cohort_index = next(i for i, c in enumerate(step.state.material.cohorts)
                                if c.cohort_id == record['cohort_id'])
            stored_area = sum((Fraction(float(piece[0])) for piece in step.state.material.stock[
                step.state.material.piece_cohort == cohort_index]), Fraction(0))
            self.assertEqual(stored_area, surviving)
            for row in record['transient_consumption']:
                self.assertEqual(Fraction(row['amounts'][0]), Fraction(row['area_m2']))
                self.assertEqual(len(row['amounts']), len(state.material.columns))
                self.assertIn(row['boundary_id'], TRENCHES)
        self.assertTrue(step.state.material.closure()['identity_exact'])
        again = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
        self.assertEqual(again.state_id, step.state.state_id)

    def test_signed_heat_and_split_sink_destinations_include_the_transient_share(self):
        exteriors = (('mantle-source', 'source'), ('slab-a', 'sink'), ('slab-b', 'sink'))
        state = F.crust(world(), exteriors=exteriors)
        proposed = motion(supplies=ridge_supplies(enthalpy_per_area_j_m2=-F.D3_ENTHALPY_PER_AREA),
                          sinks=tuple(F.sink(name, tuple(zip(('slab-a', 'slab-b'), CONTROL['split_sink_fractions'])))
                                      for name in TRENCHES))
        step = T.advance(state, proposed, end_time_s=MYR)
        records = transient_births(step)
        self.assertGreater(len(records), 0)
        for record in records:
            for row in record['transient_consumption']:
                self.assertLess(Fraction(row['amounts'][-1]), 0)
        supplied = step.state.material.supplied()
        for column in state.material.columns[1:]:
            self.assertEqual(supplied['slab-b'][column], 3*supplied['slab-a'][column])
        self.assertTrue(step.state.material.closure()['identity_exact'])

    def test_restore_refuses_changed_transient_geometry_amount(self):
        state = F.crust(world())
        step = T.advance(state, motion(), end_time_s=MYR)
        arrays = {name: np.array(value, copy=True) for name, value in step.arrays().items()}
        name = next(name for name in arrays if name.endswith('transient_area_m2'))
        arrays[name][0] *= 2
        with self.assertRaisesRegex(L.LedgerError, 'transient source-to-sink rows'):
            T.restored(state, {'sphere': step.record(), 'transfers': []}, arrays)


class TransientLedgerTests(unittest.TestCase):
    def test_finite_stock_legs_are_atomic_replayable_and_allow_continuation(self):
        with threadpool_limits(limits=1, user_api='blas'), tempfile.TemporaryDirectory() as folder:
            prepared = F2.preparation()
            # The extra outer ridge makes this control draw about 9.58 kg A and
            # 4.79 kg B. Declare ten times the retained store-a stock, preserving
            # its composition and signed heat. The 100-fold A request below is
            # still exhausting; availability admission itself is unchanged.
            stocks = F2.reservoirs(component_mass_kg=CONTROL['finite_component_mass_kg'],
                                   enthalpy_j=CONTROL['finite_enthalpy_j'])
            column = F2.root(F.control('clock_commit')['column_steps'], prepared=prepared,
                             stocks=stocks, basis=F2.BASIS)
            pieces = STOCK['pieces']
            state = F.state(world(ledger=True), phases=tuple(pieces['phases']), basis=F2.BASIS,
                            stock_link=dict(STOCK['stock_link']), exteriors=F.EXTERIORS,
                            mass_per_area_kg_m2=dict(pieces['mass_per_area_kg_m2']),
                            thickness_m=dict(pieces['thickness_m']),
                            enthalpy_per_area_j_m2=pieces['enthalpy_per_area_j_m2'])
            supply = STOCK['supply']
            supplies = ridge_supplies(source=supply['source'], stock=True,
                                       mass_per_area_kg_m2=dict(supply['mass_per_area_kg_m2']),
                                       thickness_m=dict(supply['thickness_m']),
                                       enthalpy_per_area_j_m2=supply['enthalpy_per_area_j_m2'])
            proposed = motion(supplies=supplies, sinks=tuple(
                F.sink(name, ((STOCK['return_to'], 1., True),)) for name in TRENCHES))
            greedy = dataclasses.replace(proposed, supplies=(dataclasses.replace(
                supplies[0], mass_per_area_kg_m2=dict(STOCK['exhausting_mass_per_area_kg_m2'])), *supplies[1:]))
            path = Path(folder)/'ledger.sqlite'
            store = F2.store(path)
            try:
                ledger, root = L.Ledger.create(store, column,
                                               exteriors=tuple(tuple(row) for row in STOCK['exchange_exteriors']),
                                               sphere=state)
                deadline = lambda: time.perf_counter()+F.CASE['resources']['clock_deadline_s']
                refused = K.Clock(ledger).advance(steps=1, deadline=deadline(), transfers=(greedy,))
                self.assertEqual((refused.status, refused.accepted_steps, refused.head.key),
                                 (K.REFUSED_EXCHANGE, 0, root.key), refused.reason)
                self.assertIn('finite availability', refused.reason)
                self.assertEqual(store.statistics()['snapshots'], 1)
                result = K.Clock(ledger).advance(steps=1, deadline=deadline(), transfers=(proposed,))
                self.assertEqual(result.status, K.COMPLETED, result.reason)
                self.assertTrue(ledger.sphere(result.head).material.closure()['identity_exact'])
                self.assertTrue(ledger.exchange(result.head).closure()['identity_exact'])
                self.assertTrue(any(row.get('transient_consumption')
                                    for row in result.head.metadata()['sphere']['births']))
                transfers = result.head.metadata()['transfers']
                self.assertTrue(any(row['donor'] == supply['source'] for row in transfers))
                self.assertTrue(any(row['receiver'] == STOCK['return_to'] for row in transfers))
                accepted_id = ledger.sphere(result.head).state_id
                ledger_id = ledger.ledger_id
            finally:
                store.close()
            store = F2.store(path)
            try:
                reopened = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(reopened.verify_chain().key, result.head.key)
                self.assertEqual(reopened.sphere(result.head).state_id, accepted_id)
                still = T.Motion(1, 2, {plate: F.IDENTITY for plate in state.network.plate_ids})
                continuation = K.Clock(reopened).advance(steps=1, deadline=deadline(), transfers=(still,))
                self.assertEqual(continuation.status, K.COMPLETED, continuation.reason)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
