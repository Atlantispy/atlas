"""Bounded exact topography parity; synthetic parameters are not Diadem input."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import unittest
from unittest.mock import patch

from work.geology_r1 import native as g1
from work.topography_r1 import kernels, transport
from work.test_r14_transport import fixture as soil_fixture, EVIDENCE, run_case


def native_fixture(cells=16, layers=16, dense=False):
    _, tt = g1.ground_gate.backend()
    columns = []
    for i in range(cells):
        material = tuple(tt.Layer('silt', F(125, j+1), 2500, F(2, 5),
                         'mobile_sediment', EVIDENCE) for j in range(layers))
        columns.append((f'c{i:02}', tt.Column(1, (cells-i)*100, material, 'SYNTHETIC TEST')))
    state = tt.LandscapeState(tuple(columns))
    edges = []
    for i in range(cells-1):
        for j in range(i+1, min(cells, i+(8 if dense else 2))):
            edges.append(tt.Connector(f'e{i:02}-{j:02}', f'c{i:02}', f'c{j:02}',
                                      (j-i)*100, None, EVIDENCE))
    edges.append(tt.Connector('out', f'c{cells-1:02}', None, 100, 0, EVIDENCE))
    prop = lambda name, value, unit: tt.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
    laws = (tt.ErosionLaw('silt', 'mobile_sediment',
                         prop('erosion_coefficient_at_reference_runoff', 0.000001, '1/year'),
                         prop('reference_runoff', 1, 'm/year')),)
    settling = (tt.SedimentLaw('silt', 10000, F(2, 5), 0, EVIDENCE),)
    return (state, {key: F(1) for key, _ in columns}, tuple(edges), laws, settling), {
        'duration_years': F(1, 1000), 'controls': tt.TrialControls(F(1, 2), F(1, 5), EVIDENCE),
        'evidence_id': EVIDENCE}


def scientific_trial(value):
    receipt = dict(value.receipt)
    receipt.pop('numerical_composition')
    return replace(value, receipt=receipt)


def scientific_transport(value):
    result = deepcopy(value)
    result['ledger']['terrain'].pop('numerical_composition')
    return result


def transport_kwargs(case):
    return dict(duration_s=1., seconds_per_year=100.,
        controls={'max_relief_change_fraction': .5, 'max_solid_liquid_ratio': .2, 'evidence': EVIDENCE},
        soil_controls=case[5], evidence=EVIDENCE)


def switching_fixture():
    from work.generator_upgrade_r13 import soil
    case = soil_fixture()
    cells = case[0]
    cells['a']['model']['layers'][0]['thickness_m'] = 2.
    cells['a']['materials'][0]['dry_mass_kg_m2'] = 2500.
    cells['a']['soil'] = soil.initial_state(cells['a']['model'], [-1.], [280.])
    cells['b']['base_elevation_m'] = 5.875
    cells['c'] = deepcopy(cells['b'])
    cells['c']['base_elevation_m'] = -.125
    def edge(name, source, target, length=1., level=None):
        return dict(connector_id=name, source_id=source, receiver_id=target,
                    length_m=length, outlet_elevation_m=level, evidence=EVIDENCE)
    for law in case[3]:
        law['settling_m_year'] = 0.
    return (cells, [edge('ab', 'a', 'b'), edge('ac', 'a', 'c', 2.),
                   edge('bc', 'b', 'c'), edge('out', 'c', None, level=-1.)], *case[2:])


class KernelTests(unittest.TestCase):
    def test_route_exact_tie_and_positive_water_pit(self):
        args, kw = native_fixture(4, 8, True)
        state, runoff, edges = args[:3]
        _, tt = g1.ground_gate.backend()
        a = tt.route_water(state, runoff, edges, duration_years=kw['duration_years'])
        b = kernels.route_water(state, runoff, edges, duration_years=kw['duration_years'])
        self.assertEqual(a, b)
        self.assertEqual(b['selected']['c00'][1].connector_id, 'e00-01')
        with self.assertRaisesRegex(tt.TerrainRegimeError, 'no downhill'):
            kernels.route_water(state, runoff, (), duration_years=kw['duration_years'])

    def test_native_parity_origins_and_all_feature_switches(self):
        args, kw = native_fixture(8, 8, True)
        before = args[0].as_dict()
        reference = scientific_trial(g1.terrain.trial(*args, **kw))
        for geometry, settling in ((False, True), (True, False), (True, True)):
            actual = kernels._trial(*args, **kw, geometry=geometry, settling=settling)
            self.assertEqual(reference, scientific_trial(actual))
        self.assertEqual(before, args[0].as_dict())
        origins = {(r['source_cell'], r['source_layer_index']) for r in reference.erosion_events}
        self.assertEqual(len(origins), 8)
        self.assertGreater(len(reference.receipt['sediment_transfers']), len(origins))
        self.assertTrue(all(r['mass_residual_kg'] == r['solid_residual_m3'] == 0
                            for r in reference.receipt['material_balances']))

    def test_local_geometry_invalidation_and_route_token_guards(self):
        args, kw = native_fixture(3, 4)
        state, runoff, edges = args[:3]
        tt, view, _, route = kernels._scope(True)
        first = view.columns(state)
        self.assertIs(first, view.columns(state))
        key, column = state.columns[0]
        changed = replace(state, columns=((key, replace(column, basal_elevation_m=column.basal_elevation_m+1)), *state.columns[1:]))
        self.assertEqual(view.surface(view.columns(changed), key)-view.surface(first, key), 1)
        token = kernels._RouteReuse(tt, route, state, runoff, edges, kw['duration_years'])
        for malformed in (dict(runoff, c00=True), dict(runoff, c00='1')):
            with self.assertRaises(tt.TerrainContractError):
                token.take(state, malformed, edges, duration_years=kw['duration_years'])
        with self.assertRaises(tt.TerrainContractError):
            token.take(state, runoff, iter(edges), duration_years=kw['duration_years'])
        with self.assertRaises(tt.TerrainContractError):
            token.take(state, runoff, edges, duration_years='1/1000')
        with self.assertRaisesRegex(ValueError, 'bound and single-use'):
            token.take(changed, runoff, edges, duration_years=kw['duration_years'])
        original_flow = deepcopy(token.flow)
        token.flow['discharge_m3_year']['c00'] += 1
        with self.assertRaisesRegex(ValueError, 'bound and single-use'):
            token.take(state, runoff, edges, duration_years=kw['duration_years'])
        token.flow = original_flow
        original_route = token.route
        token.route = lambda *a, **k: original_flow
        with self.assertRaisesRegex(ValueError, 'callable/source identity'):
            token.take(state, runoff, edges, duration_years=kw['duration_years'])
        token.route = original_route
        self.assertIs(token.take(state, runoff, edges, duration_years=kw['duration_years']), token.flow)
        with self.assertRaisesRegex(ValueError, 'bound and single-use'):
            token.take(state, runoff, edges, duration_years=kw['duration_years'])

    def test_settling_branch_rejection_preserved(self):
        args, kw = native_fixture(2, 1)
        _, tt = g1.ground_gate.backend()
        invalid = (tt.SedimentLaw('silt', F(1, 2**100), F(2, 5), 0, EVIDENCE),)
        with self.assertRaisesRegex(tt.TerrainContractError, 'positive transport/deposition branch'):
            kernels.trial(*args[:4], invalid, **kw)

    def test_coupled_exact_parity_and_distinct_changed_geometry_route(self):
        case = switching_fixture()
        before = deepcopy(case)
        expected = scientific_transport(run_case(case))
        actual = transport.step(*case[:5], **transport_kwargs(case))
        self.assertEqual(expected, scientific_transport(actual))
        self.assertEqual(actual['routes_before']['receivers']['a'], 'b')
        self.assertEqual(actual['routes_after']['receivers']['a'], 'c')
        self.assertEqual(before, case)
        self.assertEqual(actual['routes_after'], transport.routes(actual['cells'], case[1], seconds_per_year=100.))


if __name__ == '__main__':
    unittest.main()
