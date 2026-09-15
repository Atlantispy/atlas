"""Tiny continuing-state integration regressions; no physical case execution."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import unittest

from work.geology_r1 import composite
from work.native_terrain_r1 import evolve as e, materials as m, provenance as p
from work.native_terrain_r1.domain import Domain
from work.native_terrain_r1.receiver import FiniteReceiver
from work.native_terrain_r1.test_materials import fixture, controls, apply, face
from work.terrain_model_r7.hillslope_kernel import Grid


EVIDENCE = 'SYNTHETIC TEST tiny native coupling regression'
EXCLUSIONS = {'weathering', 'uplift', 'rock_failure', 'pore_water', 'enthalpy', 'seasonal_forcing'}
CLOCK = {'calendar_id': 'synthetic-year', 'seconds_per_year': '31557600', 'evidence': EVIDENCE}


def connection(*, diffusion=F(1, 2**14), erosion=F(1, 2**30), critical=None,
               receiver=None, mass_quantum=F(1, 2**40)):
    """Four connected supports; true rock/weathered/two mobile identities."""
    state, old_palette, old_packing, _ = fixture()
    tt = m.native()
    palette, ids = {}, {}
    for mid, descriptor in old_palette.items():
        parts = [{key: row[key] for key in ('unit_id', 'bulk_weight', 'grain_density_kg_m3', 'porosity')}
                 for row in descriptor['constituents']]
        coefficient = erosion if descriptor['phase'] == 'mobile_sediment' else F()
        new = composite.create(parts, str(coefficient), phase=descriptor['phase'],
                               evidence=descriptor['evidence'])
        palette[new['material_id']] = new
        ids[mid] = new['material_id']
    state = replace(state, columns=tuple((key, replace(column,
        basal_elevation_m=F(40 - 10 * index),
        layers=tuple(replace(layer, material_id=ids[layer.material_id]) for layer in column.layers)))
        for index, (key, column) in enumerate(state.columns)))
    packing = {ids[mid]: value for mid, value in old_packing.items()}
    cell_ids = tuple('abcd')
    edges = []
    for i, key in enumerate(cell_ids):
        row, col = divmod(i, 2)
        for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            rr, cc = row + dr, col + dc
            if 0 <= rr < 2 and 0 <= cc < 2:
                other = cell_ids[rr * 2 + cc]
                edges.append(tt.Connector(key + '-' + other, key, other, F(1), None, EVIDENCE))
    edges.append(tt.Connector('toe', 'd', None, F(1), F(0), EVIDENCE))
    def prop(name, value, unit):
        return tt.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
    laws, sediment = [], []
    for order, (mid, descriptor) in enumerate(sorted(palette.items())):
        phases = {descriptor['phase'], 'mobile_sediment'}
        for phase in sorted(phases):
            coefficient = erosion if phase == 'mobile_sediment' and descriptor['phase'] == phase else F()
            laws.append(tt.ErosionLaw(mid, phase,
                prop('erosion_coefficient_at_reference_runoff', coefficient, '1/year'),
                prop('reference_runoff', 1, 'm/year')))
        sediment.append(tt.SedimentLaw(mid, F(1), F(descriptor['porosity']), order, EVIDENCE))
    executor = e.Executor(Domain(Grid(2, 2, 1, 1), cell_ids, tuple(edges)),
        [float(diffusion)] * 4, critical, packing,
        controls(mass_quantum), e.UniformRunoff(F(1, 10), EVIDENCE),
        tuple(laws), tuple(sediment), tt.TrialControls(F(1, 2), F(1, 5), EVIDENCE),
        receiver=receiver, evidence=EVIDENCE, disabled_processes=EXCLUSIONS)
    envelope = e.from_synthetic(state, palette, CLOCK, reference_runoff_m_year=F(1), evidence=EVIDENCE)
    acceptance = e.Acceptance(F(1, 100), F(1, 10), F(1, 10**8), 4, EVIDENCE)
    return executor, envelope, acceptance


class ContinuingStateTests(unittest.TestCase):
    def test_connected_transport_incises_and_preserves_exact_origin_time_runoff(self):
        executor, envelope, acceptance = connection()
        original = deepcopy(envelope)
        result = executor.advance(envelope, F(1), acceptance, operation_id='connected-one')
        body = e.validate(result)
        state = m.native().LandscapeState.from_dict(body['state'])
        initial = m.native().LandscapeState.from_dict(envelope['body']['state'])
        self.assertEqual(envelope, original)
        self.assertEqual(state.elapsed_years, F(1))
        self.assertEqual(len(body['history']), 1)
        substeps = body['history'][0]['substeps']
        self.assertEqual(sum(F(row['surface_runoff_m3']) for row in substeps), F(2, 5))
        self.assertEqual(F(body['surface_water_exported_m3']), F(2, 5))
        self.assertTrue(any(row['hillslope']['transfers'] for row in substeps))
        self.assertTrue(any(F(balance['exported_mass_kg']) > 0 for row in substeps
                            for balance in row['channel']['material_balances']))
        self.assertNotEqual(state.column_map['a'].surface_m, initial.column_map['a'].surface_m)
        for key in initial.column_map:
            before = [layer for layer in initial.column_map[key].layers if layer.phase != 'mobile_sediment']
            after = [layer for layer in state.column_map[key].layers if layer.phase != 'mobile_sediment']
            self.assertEqual(after, before)
        totals = {origin: F(body['exported_origin_mass_kg'].get(origin, 0)) for origin in body['origins']}
        for rows in body['lineage'].values():
            for sources in rows:
                for origin, mass in sources.items():
                    totals[origin] += F(mass)
        self.assertEqual(totals, {origin: F(row['mass_kg']) for origin, row in body['origins'].items()})

    def test_zero_law_full_and_half_steps_are_identical(self):
        executor, envelope, acceptance = connection(diffusion=F(), erosion=F())
        exact = replace(acceptance, max_surface_error_m=F(), max_material_bulk_l1_error_m3=F(),
                        max_allocation_error_m3=F())
        result = executor.advance(envelope, F(1), exact, operation_id='zero')
        row = e.validate(result)['history'][0]
        self.assertEqual(F(row['diagnostics']['surface_error_m']), 0)
        self.assertEqual(F(row['diagnostics']['material_bulk_l1_error_m3']), 0)
        before = m.native().LandscapeState.from_dict(envelope['body']['state'])
        after = m.native().LandscapeState.from_dict(result['body']['state'])
        self.assertEqual([c.layers for _, c in before.columns], [c.layers for _, c in after.columns])
        self.assertEqual(after.elapsed_years, F(1))
        self.assertEqual(row['accepted_method'], 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED')

    def test_serialised_reload_and_next_step_match_exactly(self):
        executor, envelope, acceptance = connection()
        first = executor.advance(envelope, F(1), acceptance, operation_id='first')
        restored = json.loads(json.dumps(first, sort_keys=True, allow_nan=False))
        self.assertEqual(e.validate(first), e.validate(restored))
        direct = executor.advance(first, F(1), acceptance, operation_id='second')
        restarted = executor.advance(restored, F(1), acceptance, operation_id='second')
        self.assertEqual(direct, restarted)
        self.assertEqual(m.native().LandscapeState.from_dict(direct['body']['state']).elapsed_years, F(2))
        cumulative = sum(F(step['hillslope']['total_bulk_allocation_error_m3'])
                         for row in direct['body']['history'] for step in row['substeps'])
        self.assertEqual(F(direct['body']['cumulative_allocation_error_m3']), cumulative)

    def test_duplicate_and_rejected_trials_leave_input_immutable(self):
        executor, envelope, acceptance = connection()
        snapshot = deepcopy(envelope)
        exact = replace(acceptance, max_surface_error_m=F(), max_material_bulk_l1_error_m3=F(),
                        max_halvings=0)
        with self.assertRaisesRegex(ValueError, 'refinement budget'):
            executor.advance(envelope, F(1), exact, operation_id='reject')
        self.assertEqual(envelope, snapshot)
        accepted = executor.advance(envelope, F(1), acceptance, operation_id='once')
        accepted_snapshot = deepcopy(accepted)
        with self.assertRaisesRegex(ValueError, 'replay'):
            executor.advance(accepted, F(1), acceptance, operation_id='once')
        self.assertEqual(accepted, accepted_snapshot)

    def test_hillside_cfl_refines_but_critical_regime_does_not(self):
        executor, envelope, acceptance = connection(diffusion=F(1, 16), erosion=F())
        broad = replace(acceptance, max_surface_error_m=F(100), max_material_bulk_l1_error_m3=F(1000))
        result = executor.advance(envelope, F(4), broad, operation_id='cfl')
        row = e.validate(result)['history'][0]
        self.assertLess(F(row['duration_years']), F(4))
        self.assertTrue(any(r.get('kind') == 'HillslopeStepTooLarge' for r in row['rejected_trials']))
        invalid, original, accepted = connection(diffusion=F(1, 16), erosion=F(), critical=[.01] * 4)
        with self.assertRaisesRegex(ValueError, 'critical-gradient'):
            invalid.advance(original, F(1), accepted, operation_id='critical')
        self.assertEqual(original['body']['history'], [])

    def test_globally_exhausted_mobile_material_keeps_declared_packing(self):
        state, palette, packing, _ = fixture()
        exhausted = apply(state, palette, packing, [face('all-out', 0, None, 100)]).state
        view = m.hillside_view(exhausted, tuple('abcd'), Grid(2, 2, 1, 1), palette, packing)
        self.assertEqual(view['available_bulk_m3'], [0.] * 4)
        self.assertEqual(view['receiving_expansion_max'], 1.)

    def test_origin_validation_rejects_unknown_and_negative_export(self):
        _, envelope, _ = connection(diffusion=F(), erosion=F())
        body = deepcopy(envelope['body'])
        body['exported_origin_mass_kg']['unknown-origin'] = '1'
        state = m.native().LandscapeState.from_dict(body['state'])
        with self.assertRaises(ValueError):
            e._lineage_check(body, state)
        body = deepcopy(envelope['body'])
        origin = next(iter(body['origins']))
        body['exported_origin_mass_kg'][origin] = '-1'
        with self.assertRaises(ValueError):
            e._lineage_check(body, state)

    def test_finite_receiver_exact_water_solid_bounds_and_source_exhaustion(self):
        receiver = FiniteReceiver('test-receiver', F(100), F(-20), F(-1), F(0),
                                  F(1), F(2, 5), F(2, 5), EVIDENCE)
        account = receiver.account(F(1, 5), F(1, 10))
        self.assertEqual(account['free_water_m3'] + account['pore_water_m3'], F(6, 5))
        self.assertEqual(account['sediment_bulk_m3'] * F(3, 5), F(1, 10))
        with self.assertRaisesRegex(ValueError, 'source exhausted'):
            receiver.account(F(2, 5) + F(1, 2**40), F())
        with self.assertRaisesRegex(ValueError, 'drying|overflow|backwater'):
            receiver.account(F(), F(10))
        executor, envelope, acceptance = connection(diffusion=F(), erosion=F(), receiver=receiver)
        first = executor.advance(envelope, F(1), acceptance, operation_id='finite-source')
        self.assertEqual(F(first['body']['receiver']['cumulative_liquid_m3']), F(2, 5))
        snapshot = deepcopy(first)
        with self.assertRaisesRegex(ValueError, 'source exhausted'):
            executor.advance(first, F(1), acceptance, operation_id='beyond-source')
        self.assertEqual(first, snapshot)


if __name__ == '__main__':
    unittest.main(verbosity=2)
