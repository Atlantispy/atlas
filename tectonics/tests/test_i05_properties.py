"""I05.3 current properties and the lateral-heat rule (tectonics/docs/I05_MOVING_STATE.md).

Lateral-heat admission parity: the package reproduction of the MC-06 omission bound equals
tools/check_i01_lateral_heat.py (R-5, no tool moved). The tool is imported here only.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import importlib.util
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1]/'tools'/'check_i01_lateral_heat.py'
SPEC = importlib.util.spec_from_file_location('i05_lateral_heat_parity', PATH)
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)

from atlas_tectonics import integration_thermal as H        # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import replace                             # noqa: E402
import math                                                 # noqa: E402

import numpy as np                                          # noqa: E402

import i03_fixtures as F                                    # noqa: E402
import i04_fixtures as F4                                   # noqa: E402
import i05_fixtures as X                                    # noqa: E402
from atlas_tectonics import integration_driving as D       # noqa: E402
from atlas_tectonics import integration_material as M      # noqa: E402
from atlas_tectonics import integration_ports as P         # noqa: E402
from atlas_tectonics import integration_properties as R    # noqa: E402
from atlas_tectonics import integration_transfer as T      # noqa: E402


def contact(i=0, j=1, **changes):
    out = dict(left=i, right=j, conductivity_w_m_k=3, area_m2=1, distance_m=1000)
    out.update(changes)
    return out


def window(duration=1000000, bounds=None, kind='declared_whole_window'):
    return dict(duration_s=duration, envelope=dict(kind=kind, difference_bounds_k=[100] if bounds is None else bounds,
                                                   basis='authored whole-window analytical bound'))


def outcome(function, *args, **kwargs):
    try:
        return 'ok', function(*args, **kwargs)
    except ValueError as exc:                      # the tool raises ValueError; LateralRefused is a ValueError
        return 'refused', str(exc)


class LateralAdmissionParity(unittest.TestCase):
    def pair(self, capacities, contacts):
        return (H.LateralNetwork(capacities, contacts, assumptions=dict(H.LATERAL_ASSUMPTIONS)),
                tool.Network(capacities, contacts, assumptions=dict(tool.ASSUMPTIONS)))

    def test_assumptions_and_policy_are_the_tools(self):
        self.assertEqual(H.LATERAL_ASSUMPTIONS, tool.ASSUMPTIONS)
        self.assertEqual(H.LATERAL_POLICY, {k: v for k, v in tool.POLICY.items() if k != 'oracle_relative'})

    def test_admission_matches_including_restart_carry_and_uncertified_envelopes(self):
        ours, theirs = self.pair([2000000, 5000000], [contact()])
        runs = [([window()], dict(temperature_allowance_k=Q(3, 20))),
                ([window()], dict(temperature_allowance_k=Q(3, 20)-Q(1, 10**20))),
                ([window(), window()], dict(temperature_allowance_k=Q(1, 5))),
                ([window()], dict(temperature_allowance_k=Q(1, 5), initial_error_bound_k=Q(3, 20))),
                ([window(duration=2000000)], dict(temperature_allowance_k=1)),
                ([window(bounds=[0], kind='samples_only')], dict(temperature_allowance_k=1000)),
                ([window(), window(kind='unknown')], dict(temperature_allowance_k=1000))]
        statuses = []
        for windows, kwargs in runs:
            got, expected = H.lateral_admission(ours, windows, **kwargs), tool.admission(theirs, windows, **kwargs)
            self.assertEqual(got, expected)
            statuses.append(got['status'])
        self.assertEqual(set(statuses), {'PASS_CONDITIONAL_THERMAL_BOUND', 'REFUSED_TEMPERATURE_BUDGET',
                                         'REFUSED_UNCERTIFIED_ENVELOPE'})
        # The bound is a maximum over cells: each contact heats both of its ends, so the smaller-capacity cell may
        # be either endpoint; three cells put it on the right of one contact and the left of the other.
        three, three_tool = self.pair([5000000, 2000000, 7000000], [contact(), contact(1, 2, area_m2=3)])
        windows = [window(bounds=[100, 40])]
        self.assertEqual(H.lateral_admission(three, windows, temperature_allowance_k=1),
                         tool.admission(three_tool, windows, temperature_allowance_k=1))
        self.assertEqual(three.residual_bound([100, 40]), Q(3*100+9*40, 1000)/2000000)
        whole = H.lateral_admission(ours, [window(), window()], temperature_allowance_k=Q(1, 5))
        first = H.lateral_admission(ours, [window()], temperature_allowance_k=Q(1, 5))
        carried = H.lateral_admission(ours, [window()], temperature_allowance_k=Q(1, 5),
                                      initial_error_bound_k=Q(first['error_bound_exact_k']))
        self.assertEqual(carried['error_bound_exact_k'], whole['error_bound_exact_k'])

    def test_refusals_match(self):
        for capacities, contacts in (([1, 2], [contact(area_m2=0)]), ([1, 2], [contact(), contact(1, 0)]),
                                     ([1, 2], [contact(left=0, right=0)]), ([], []), ([1, -2], []),
                                     ([1, float('nan')], []), ([1, 2], [dict(contact(), extra=1)])):
            self.assertEqual(outcome(H.LateralNetwork, capacities, contacts, assumptions=dict(H.LATERAL_ASSUMPTIONS)),
                             outcome(tool.Network, capacities, contacts, assumptions=dict(tool.ASSUMPTIONS)))
            self.assertEqual(outcome(H.LateralNetwork, capacities, contacts,
                                     assumptions=dict(H.LATERAL_ASSUMPTIONS))[0], 'refused')
        moving = dict(H.LATERAL_ASSUMPTIONS, geometry='moving')
        self.assertEqual(outcome(H.LateralNetwork, [1, 2], [], assumptions=moving)[0], 'refused')
        ours, theirs = self.pair([2000000, 5000000], [contact()])
        for windows, kwargs in (([], dict(temperature_allowance_k=1)),
                                ([dict(window(), extra=1)], dict(temperature_allowance_k=1)),
                                ([window(bounds=[1, 2])], dict(temperature_allowance_k=1)),
                                ([window()], dict(temperature_allowance_k=-1))):
            self.assertEqual(outcome(H.lateral_admission, ours, windows, **kwargs),
                             outcome(tool.admission, theirs, windows, **kwargs))


def port_header(port, moving, sphere, support_id, *, endpoint=None):
    network = sphere.network
    time = network.time_s if endpoint is None else endpoint
    return P.Header(port, sphere.state_id, (network.step, network.step, time, time), time, network.network_id,
                    support_id, D.datum_id(F4.datum()), moving.moving_id, network.sphere.frame_id,
                    'I05 (moving state)', 'test: tectonics/tests/test_i05_properties.py')


def uniform(top, bottom, base):
    return dict(top=top, bottom=bottom, base=base)


def undeclared(state, records, declared_step=None):
    """A moving state issued without the declaration's checks (the route a restored or drifted state takes): each
    piece's declared heat, through the private issuer."""
    by_id = {r.cohort_id: r for r in records}
    heat = [[s.declared_heat_per_area(X.T_REF)*p.area_m2 for s in by_id[p.cohort_id].sublayers]
            for p in state.material.pieces()]
    initial = sum((Q(x) for column in heat for x in column), Q(0))
    return M._issued(state, records, heat, initial, (), Q(0), Q(0), X.T_REF, Q(0), declared_step)


def dense(cohort, units, **kwargs):
    """X.record(cohort) with its reference density raised by ``units`` eps relative."""
    sublayers = tuple(replace(s, reference_density_kg_m3=2900.*(1+units*2.**-52)) for s in X.sublayers())
    return replace(X.record(cohort, **kwargs), sublayers=sublayers)


class PropertyPorts(unittest.TestCase):
    """I05.3: P1 and P2 from one moving state at one common endpoint; P3 carried; direction controls."""

    @classmethod
    def setUpClass(cls):
        cls.network = F.sector_world()
        cls.state = X.crust(cls.network)
        cls.moving = X.moving(cls.state)
        cls.support = P.trace_support(cls.network)

    def p1(self, moving=None, state=None, **kwargs):
        moving, state = moving or self.moving, state or self.state
        support = P.trace_support(state.network)
        return R.moving_columns(moving, state, support, port_header('P1', moving, state, support.support_id, **kwargs),
                                F4.datum())

    def p2(self, moving=None, state=None, healing=R.HEALING_NONE, **kwargs):
        moving, state = moving or self.moving, state or self.state
        header = port_header('P2', moving, state, R.piece_support_id(state), **kwargs)
        return R.strength_port(moving, state, header, F4.datum(), healing_law_id=healing)

    def test_p1_columns_are_the_pieces_own_and_feed_the_i04_consumer(self):
        columns = self.p1()
        self.assertEqual(columns.points, 2*self.support.edges)
        self.assertFalse(np.any(columns.unknown))
        pieces = self.state.material.pieces()
        for point in range(columns.points):
            thickness, density, alpha, bottom, top = columns.layers(point)
            source = columns.sources[point]
            record = self.moving.cohort(source)
            self.assertEqual(list(density), [s.reference_density_kg_m3 for s in reversed(record.sublayers)])
            np.testing.assert_array_equal(bottom, top)                     # piecewise-constant finite-volume means
            self.assertTrue(np.all(np.diff(bottom) < 0))                    # bottom to top: hottest first
        anomaly = D.trace_anomaly(F4.datum(), columns)
        self.assertTrue(np.all(np.isfinite(anomaly)))
        self.assertEqual(len(pieces), len(self.moving.pieces))

    def test_one_common_endpoint_for_p1_and_p2(self):
        columns, strength = self.p1(), self.p2()
        for port in (columns, strength):
            self.assertEqual((port.header.parent_state_id, port.header.endpoint_s, port.header.parameter_id),
                             (self.state.state_id, self.state.network.time_s, self.moving.moving_id))
        for function in (self.p1, self.p2):
            with self.assertRaises(P.PortRefused) as caught:
                function(endpoint=self.state.network.time_s+1.)
            self.assertIn(caught.exception.code, (P.UNSUPPORTED, P.MISSING_VALUE))

    def test_heating_one_cohort_moves_the_properties_in_the_declared_direction(self):
        """Predeclared (I05-10): +dT on one cohort keeps reference mass, lowers effective load, raises the surface;
        in one uniformly heated layer with r > r_m/2 the anomaly rises; P2 temperature rises by dT and the vertical
        stress below it falls."""
        dT = 100.
        cold = X.moving(self.state, top=600., bottom=600., base=600.)
        warm = X.moving(self.state, top=600.+dT, bottom=600.+dT, base=600.+dT)
        datum = F4.datum()
        before, after = self.p1(cold), self.p1(warm)
        for point in (0, 1):
            layers_b, layers_a = before.layers(point), after.layers(point)
            np.testing.assert_array_equal(layers_a[0], layers_b[0])        # thickness and reference mass unchanged
            np.testing.assert_array_equal(layers_a[1], layers_b[1])
            kb, ka = (D.columns(datum, *(np.asarray(v)[None, :] for v in layers)) for layers in (layers_b, layers_a))
            self.assertEqual(ka['reference_rock_mass_kg_m2'][0], kb['reference_rock_mass_kg_m2'][0])
            self.assertLess(ka['effective_rock_load_kg_m2'][0], kb['effective_rock_load_kg_m2'][0])
            self.assertGreater(ka['surface_elevation_m'][0], kb['surface_elevation_m'][0])
        one = dict(thickness_m=np.array([[7000.]]), reference_density_kg_m3=np.array([[2900.]]),
                   alpha_per_k=np.array([[3e-5]]))
        assert 2900. > datum.mantle_density_kg_m3/2
        base = D.columns(datum, top_temperature_k=np.array([[600.]]), bottom_temperature_k=np.array([[600.]]), **one)
        hot = D.columns(datum, top_temperature_k=np.array([[700.]]), bottom_temperature_k=np.array([[700.]]), **one)
        self.assertGreater(hot['gpe_anomaly_j_m2'][0], base['gpe_anomaly_j_m2'][0])
        sb, sa = self.p2(cold), self.p2(warm)
        np.testing.assert_allclose(sa.temperature_k-sb.temperature_k, dT, rtol=0, atol=1e-9)
        self.assertTrue(np.all(sa.vertical_stress_bottom_pa < sb.vertical_stress_bottom_pa))
        np.testing.assert_array_equal(sa.kappa, sb.kappa)

    def test_p2_layout_stress_and_refusals(self):
        strength = self.p2()
        self.assertEqual(strength.pieces, self.moving.pieces)
        self.assertEqual(len(strength.offsets), len(strength.pieces)+1)
        for i in range(len(strength.pieces)):
            lo, hi = int(strength.offsets[i]), int(strength.offsets[i+1])
            top, bottom = strength.vertical_stress_top_pa[lo:hi], strength.vertical_stress_bottom_pa[lo:hi]
            self.assertEqual(top[-1], 0.)                                  # zero load at the column's top
            np.testing.assert_array_equal(bottom[1:], top[:-1])            # continuous down the column
            self.assertTrue(np.all(bottom > top))
        with self.assertRaises(P.PortRefused) as caught:
            self.p2(healing='atlas.some-healing.v1')
        self.assertEqual(caught.exception.code, P.UNSUPPORTED)
        with self.assertRaises(P.PortRefused) as caught:
            self.p2(healing=None)
        self.assertEqual(caught.exception.code, P.MISSING_VALUE)
        unknown = tuple(replace(X.record(c.cohort_id), sublayers=tuple(replace(s, pore_pressure_pa=None)
                                                                         for s in X.sublayers()))
                        for c in self.state.material.cohorts)
        moving = M.declare_moving(self.state, unknown, enthalpy_reference_k=X.T_REF)
        with self.assertRaises(P.PortRefused) as caught:
            self.p2(moving)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.MISSING_VALUE, 'pore_pressure_pa'))

    def mixed(self, two=None):
        """The merged face s00-merged (beside the B|C boundary on meridian 0) holding pieces of cohorts one-C and
        two-C; ``two`` is two-C's record (by default one-C's content under its own name)."""
        from test_i05_transport import merged_face, remesh
        network = F.three_plates()
        cohort_of = {'s00-b01': 'one-C', 's00-b02': 'two-C'}
        state = X.crust(network, cohort_of=lambda f: cohort_of.get(f, 'inherited-'+network.face_plate(f)))
        records = tuple(two if two is not None and c.cohort_id == 'two-C' else X.record(c.cohort_id)
                        for c in state.material.cohorts)
        moving = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF)
        step = X.stepped(state, remesh(state, ('s00-b01', 's00-b02'), (merged_face(),)))
        return M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state, step.state

    def mixed_points(self, sphere):
        """Every trace point whose face is s00-merged (it borders the trace on two edges)."""
        owner = R._faces_of_edges(sphere.network)
        edges = [pair for boundary in sphere.network.boundaries for pair in R._pairs(boundary)]
        points = [2*e+side for e, (a, b) in enumerate(edges) for side, key in ((0, (a, b)), (1, (b, a)))
                  if owner.get(key) == 's00-merged']
        self.assertTrue(points)
        return points

    def mixed_point(self, columns, sphere):
        return self.mixed_points(sphere)[0]

    def test_a_mixed_face_of_identical_pieces_is_the_single_piece_column(self):
        """fv-cell-mean control 1 (amendment of 4 October 2026): pieces of bitwise-equal layer structure and equal
        temperatures give exactly the single piece's column, flagged with its cohort set in the port's identity."""
        after, sphere = self.mixed()
        columns = self.p1(after, sphere)
        point = self.mixed_point(columns, sphere)
        self.assertEqual(columns.representation[point], ('fv-cell-mean', ('one-C', 'two-C')))
        index = next(i for i, p in enumerate(sphere.material.pieces()) if p.face_id == 's00-merged')
        piece, record, thickness, temperature = R._piece_column(after, sphere, index)
        expected = [list(reversed(thickness)), [s.reference_density_kg_m3 for s in reversed(record.sublayers)],
                    [s.alpha_per_k for s in reversed(record.sublayers)], list(reversed(temperature)),
                    list(reversed(temperature))]
        for got, want in zip(columns.layers(point), expected):
            self.assertEqual(np.asarray(got).tobytes(), np.asarray(want, dtype=np.float64).tobytes())
        mixed = set(self.mixed_points(sphere))
        self.assertTrue(all(columns.representation[p] == columns.representation[point] for p in mixed))
        self.assertTrue(all(columns.representation[p] is None for p in range(columns.points) if p not in mixed))
        plain = self.p1()                                    # a state without mixed faces keeps its record unchanged
        self.assertIsNone(plain.representation)
        bare = P.columns_port(columns.header, columns.offsets, columns.thickness_m, columns.reference_density_kg_m3,
                              columns.alpha_per_k, columns.bottom_temperature_k, columns.top_temperature_k,
                              sources=columns.sources)
        self.assertNotEqual(bare.port_id, columns.port_id)      # the flag and the cohort set are in the identity

    def test_a_two_piece_face_gives_the_exact_enthalpy_mean(self):
        """fv-cell-mean control 2: per sublayer, T is the caloric inverse of sum(H)/sum(rho t A), formed exactly and
        rounded once; histories and kappa stay per piece."""
        after, sphere = self.mixed(X.record('two-C', top=600., bottom=900.))
        columns = self.p1(after, sphere)
        point = self.mixed_point(columns, sphere)
        pieces = [(i, p) for i, p in enumerate(sphere.material.pieces()) if p.face_id == 's00-merged']
        self.assertEqual(len(pieces), 2)
        record = after.cohort('one-C')
        heat = [after.heat_j(i).tolist() for i, _ in pieces]
        thickness = [H.column_of(after.cohort(p.cohort_id), p, sphere.material.phases)[0] for _, p in pieces]
        mean = []
        for l, s in enumerate(record.sublayers):
            total = sum((Q(heat[k][l]) for k in range(2)), Q(0))
            mass = sum((Q(s.reference_density_kg_m3*thickness[k][l]*p.area_m2) for k, (_, p) in enumerate(pieces)),
                       Q(0))
            mean.append(s.temperature(float(total/mass), X.T_REF))
        layers = columns.layers(point)
        self.assertEqual(list(layers[3]), list(reversed(mean)))
        self.assertEqual(list(layers[4]), list(reversed(mean)))
        lone = [R._piece_column(after, sphere, i)[3] for i, _ in pieces]
        self.assertTrue(all(min(a, b) < m < max(a, b) for a, b, m in zip(lone[0], lone[1], mean)))
        strength = self.p2(after, sphere)
        self.assertEqual(len(strength.pieces), len(sphere.material.pieces()))   # P2 stays per piece

    def test_a_mixed_face_of_different_layer_structure_refuses(self):
        """fv-cell-mean control 3: a different layer structure (here two-C's sublayers split 1000/2500/1750/1750 m)
        still refuses unresolved column; nothing is averaged across structures."""
        split = tuple(replace(s, thickness_m=h) for s, h in zip(X.sublayers(), (1000., 2500., 1750., 1750.)))
        after, sphere = self.mixed(replace(X.record('two-C'), sublayers=split))
        with self.assertRaises(P.PortRefused) as caught:
            self.p1(after, sphere)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.UNRESOLVED_COLUMN, 's00-merged'))

    def test_the_layer_structure_includes_the_thickness_tuple(self):
        """P1-NOTE-1 (round 2): pieces whose sublayer depths are bitwise equal but whose thicknesses differ by one ulp
        in a sublayer do not share a column, so the emitted thicknesses are every piece's, not only the first's."""
        after, sphere = self.mixed()
        held = [i for i, p in enumerate(sphere.material.pieces()) if p.face_id == 's00-merged']
        columns = [R._piece_column(after, sphere, i) for i in held]
        self.assertEqual(len(columns), 2)
        R._cell_mean(after, 's00-merged', held, columns, 0)                  # equal structure: admitted
        piece, record, thickness, temperature = columns[1]
        depths = np.cumsum(thickness).tolist()
        found = None
        for l in reversed(range(len(thickness))):
            for toward in (math.inf, -math.inf):
                changed = [float(t) for t in thickness]
                changed[l] = math.nextafter(changed[l], toward)
                if found is None and np.cumsum(changed).tolist() == depths:
                    found = changed
        self.assertIsNotNone(found, 'no one-ulp thickness change keeps every depth')
        self.assertNotEqual(found, [float(t) for t in thickness])
        with self.assertRaises(P.PortRefused) as caught:
            R._cell_mean(after, 's00-merged', held, [columns[0], (piece, record, tuple(found), temperature)], 0)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.UNRESOLVED_COLUMN, 's00-merged'))

    def test_declaration_refuses_records_that_contradict_the_i03_mass(self):
        """basal-02: at declaration, sum(rho_ref t) A per phase must equal each piece's I03 mass within
        inventory_bound(0), as a birth column's must (RB-2); a contradicting density refuses there, not intervals
        later."""
        for density in (3000., 2900.*(1+1e-6), 1000.):
            records = tuple(replace(X.record(c.cohort_id), sublayers=tuple(replace(s, reference_density_kg_m3=density)
                                                                           for s in X.sublayers()))
                            for c in self.state.material.cohorts)
            with self.assertRaises(M.TransportRefused) as caught:
                M.declare_moving(self.state, records, enthalpy_reference_k=X.T_REF)
            self.assertEqual((caught.exception.code, caught.exception.detail), (M.INCOMPATIBLE, 'reference mass'))

    def test_family_cohorts_need_the_family_datum(self):
        """basal-04: P1 and P2 of cohorts that come from a starting family are issued only under the family's datum,
        3300 kg/m3 at 293.15 K exactly (I04a's gate, STALE_IDENTITY 'datum_id')."""
        from atlas_tectonics import integration_family as FAM
        cohorts = tuple(F.cohort(name, origin_id='%s#default:%s' % (FAM.SCHEMA, name))
                        for name in ('inherited-A', 'inherited-B', 'inherited-C'))
        state = X.crust(self.network, cohorts=cohorts)
        moving = X.moving(state)
        for other in (replace(F4.datum(), mantle_density_kg_m3=3250.),
                      replace(F4.datum(), reference_temperature_k=273.15),               # RB-3: T_ref alone
                      replace(F4.datum(), reference_temperature_k=math.nextafter(293.15, math.inf))):
            self.refused_datum(state, moving, other)
        self.assertEqual(self.p1(moving, state).header.datum_id, D.datum_id(F4.datum()))

    def refused_datum(self, state, moving, other):
        for port, support_id in (('P1', P.trace_support(self.network).support_id), ('P2', R.piece_support_id(state))):
            header = P.Header(port, state.state_id, (state.network.step, state.network.step, state.network.time_s,
                                                     state.network.time_s), state.network.time_s,
                              state.network.network_id, support_id, D.datum_id(other), moving.moving_id,
                              state.network.sphere.frame_id, 'I05 (moving state)', 'test: family datum')
            with self.assertRaises(P.PortRefused) as caught:
                if port == 'P1':
                    R.moving_columns(moving, state, P.trace_support(self.network), header, other)
                else:
                    R.strength_port(moving, state, header, other, healing_law_id=R.HEALING_NONE)
            self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'datum_id'))

    def test_p3_is_carried_and_rechecked_never_derived(self):
        columns = self.p1()
        core = dict(material='test:core', basis='test: authored', depth_reference='rock_surface', top_depth_m=1000.,
                    bottom_depth_m=5000., young_pa=7e10, poisson=0.25)
        self.assertEqual(R.carried_core(core, columns), core)
        with self.assertRaises(P.PortRefused) as caught:
            R.carried_core(dict(core, bottom_depth_m=8000.), columns)
        self.assertEqual(caught.exception.detail, 'REFUSED_CORE_OUTSIDE_ROCK')
        with self.assertRaises(P.PortRefused):
            R.carried_core(dict(core, elastic_thickness_m=20e3), columns)
        with self.assertRaises(P.PortRefused) as caught:                  # R-6 deferred: P4 stays reserved
            P.Header('P4', self.state.state_id, (0, 0, 0., 0.), 0., self.network.network_id, self.moving.moving_id,
                     None, self.moving.moving_id, self.network.sphere.frame_id, 'I05', 'test')
        self.assertEqual(caught.exception.code, P.UNSUPPORTED)

    def test_p3_declaration_refusals_are_the_tools_in_its_order(self):
        """Every I01_ELASTIC_CORE section 6 declaration refusal, with the tool's code (parity; the tool is imported
        here only); an admitted core is carried unchanged."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
        import check_i01_elastic_core as core_tool
        columns = self.p1()
        core = dict(material='test:core', basis='test: authored', depth_reference='rock_surface', top_depth_m=1000.,
                    bottom_depth_m=5000., young_pa=7e10, poisson=0.25)
        without_top = {k: v for k, v in core.items() if k != 'top_depth_m'}
        cases = [core, dict(core, top_depth_m=6000.), dict(core, top_depth_m=-1.), dict(core, young_pa=0.),
                 dict(core, young_pa=-1.), dict(core, young_pa='7e10'), dict(core, poisson=.7),
                 dict(core, poisson=math.nan), dict(core, bottom_depth_m=-math.inf), dict(core, bottom_depth_m=True),
                 dict(core, material=''), dict(core, basis=None), dict(core, bottom_depth_m=[5000., 6000.]),
                 dict(core, bottom_depth_m=math.nan), without_top, dict(core, layers=[]),
                 dict(core, depth_reference='sea_level'), dict(core, elastic_thickness_m=2e4), [core, core], 'core',
                 dict(core, young_pa=1e300, bottom_depth_m=6999.)]
        for case in cases:
            try:
                core_tool.elastic_core(case)
                expected = None
            except core_tool.Refusal as exc:
                expected = exc.code
            with self.subTest(case=case):
                if expected is None:
                    self.assertEqual(R.carried_core(case, columns), case)
                else:
                    with self.assertRaises(P.PortRefused) as caught:
                        R.carried_core(case, columns)
                    self.assertEqual(caught.exception.detail, expected)
        self.assertGreater(sum(1 for case in cases if not isinstance(case, dict) or case is not core), 15)

    def test_p2_refuses_a_column_that_fails_the_inventory_guard(self):
        """P2 uses P1's column representation, so it refuses wherever P1's inventory guard refuses. Declaration now
        refuses such records (basal-02), so the guard is reached here by a state issued without the declaration's
        checks, as a restored or drifted state would be."""
        for density in (3000., 2900.*(1+1e-6), 1000.):
            records = tuple(replace(X.record(c.cohort_id), sublayers=tuple(replace(s, reference_density_kg_m3=density)
                                                                           for s in X.sublayers()))
                            for c in self.state.material.cohorts)
            moving = undeclared(self.state, records)
            for function in (self.p1, self.p2):
                with self.assertRaises(P.PortRefused) as caught:
                    function(moving)
                self.assertEqual((caught.exception.code, caught.exception.detail),
                                 (P.INCOMPATIBLE_SUPPORT, 'reference mass'), (density, function.__name__))

    def test_the_inventory_bound_is_re_derived_per_step_since_declaration(self):
        """basal-05 (ruling (B)): the guard bound is (3.5 + (k + 1)) eps, k the steps since the moving state's
        declaration; it equals its formula at k = 0, and a density perturbation just beyond the step-k bound refuses
        while one within it passes."""
        eps = 2.**-52
        self.assertEqual(R.inventory_bound(0), 4.5*eps)
        self.assertEqual(R.inventory_bound(10), 14.5*eps)
        piece = self.state.material.pieces()[0]
        phases = self.state.material.phases

        def guarded(units, intervals):
            sublayers = tuple(replace(s, reference_density_kg_m3=2900.*(1+units*eps)) for s in X.sublayers())
            record = replace(X.record(piece.cohort_id), sublayers=sublayers)
            thickness = H.column_of(record, piece, phases)[0]
            R.inventory_guard(record, piece, thickness, phases, intervals)
        guarded(9, 10)                                   # within (3.5 + 11) eps whatever the roundings (<= 5 eps)
        for units, intervals in ((20, 10), (12, 0)):     # beyond the step-k bound by more than the roundings
            with self.assertRaises(P.PortRefused) as caught:
                guarded(units, intervals)
            self.assertEqual((caught.exception.code, caught.exception.detail),
                             (P.INCOMPATIBLE_SUPPORT, 'reference mass'))

    def test_a_correct_long_run_passes_the_guard_and_the_declaration_step_is_bound(self):
        """basal-05: 20 intervals of plate A turning 0.25 degrees between a ridge and a trench (births and
        consumption, I03 rounding mass and volume separately each interval): P2's guard passes at k = 20 with the
        measured drift inside the bound; declared_step is in the record, so an edit of it does not restore."""
        network = F.three_plates()
        state = X.crust(network)
        moving = X.moving(state)
        for k in range(20):
            step = X.stepped(state, X.motion(.25, step=k))
            moving = M.advance_moving(moving, state, step, X.advance(k)).state
            state = step.state
        self.assertEqual((moving.step, moving.declared_step), (20, 0))
        strength = self.p2(moving, state)
        self.assertEqual(len(strength.pieces), len(state.material.pieces()))
        drift = 0.
        for i, piece in enumerate(state.material.pieces()):
            _, record, thickness, _ = R._piece_column(moving, state, i)
            masses = dict(zip(state.material.phases, piece.mass_kg))
            held = math.fsum(s.reference_density_kg_m3*t*piece.area_m2 for s, t in zip(record.sublayers, thickness))
            drift = max(drift, abs(held-masses['crust'])/masses['crust'])
        self.assertLessEqual(drift, R.inventory_bound(20))
        print('basal-05 long run: max |sum(rho t A) - M|/M after 20 intervals = %.3f eps (bound %.1f eps)'
              % (drift/2.**-52, R.inventory_bound(20)/2.**-52))
        record = dict(moving.descriptor(), declared_step=5)
        with self.assertRaises(M.TransportRefused):
            M.restore_moving(record, moving.arrays(), state)
        self.assertEqual(M.restore_moving(moving.descriptor(), moving.arrays(), state).declared_step, 0)
        later = M._issued(state, moving.cohorts, [moving.heat_j(i).tolist() for i in range(len(moving.pieces))],
                          moving._initial, moving._supplied, moving._rounding, moving._allowance,
                          moving.enthalpy_reference_k, moving._lateral_error, 20)
        self.assertNotEqual(later.moving_id, moving.moving_id)          # the declaration step is in the identity

    def test_every_declared_or_born_record_passes_p1_at_its_first_step(self):
        """RB-2 / P1-SHOULD-2: declaration uses P1's own row arithmetic and inventory_bound(0), so a record that
        declaration admits passes P1 and P2 at k = 0; a born piece is checked by the same guard at its birth step,
        so a birth that is admitted passes P2 at the endpoint."""
        admitted = 0
        for units in (0, 2, 4, 6, 9, 20, -6):
            records = tuple(dense(c.cohort_id, units) for c in self.state.material.cohorts)
            try:
                moving = M.declare_moving(self.state, records, enthalpy_reference_k=X.T_REF)
            except M.TransportRefused as exc:
                self.assertEqual((exc.code, exc.detail), (M.INCOMPATIBLE, 'reference mass'))
                continue
            admitted += 1
            self.p1(moving)
            self.p2(moving)
        self.assertTrue(1 <= admitted < 7)
        network = F.three_plates()
        state = X.crust(network)
        moving = X.moving(state)
        born, refused = 0, {}
        for units in (0, 3, 4, 6, 12):
            sublayers = tuple(replace(s, reference_density_kg_m3=2900.*(1+units*2.**-52)) for s in X.sublayers(
                X.T_BASE, X.T_BASE))
            column = M.BirthColumn('test:birth-profile', X.SOURCE, sublayers, X.T_SURFACE, X.T_BASE)
            step = X.stepped(state, X.motion())
            try:
                out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, births=((X.BIRTH_HISTORY,
                                                                                           column),))).state
            except M.TransportRefused as exc:
                self.assertEqual(exc.code, M.INCOMPATIBLE)
                refused[units] = exc.detail
                continue
            born += 1
            self.p2(out, step.state)
        self.assertTrue(1 <= born < 5)
        # Each check fires on its own: 4 eps passes the supply check (inventory_bound(0) = 4.5 eps) and is refused by
        # P1's guard on the born piece; 6 and 12 eps, within the old 4(n+2) eps = 24 eps, are refused by the supply
        # check itself.
        self.assertEqual(refused, {4: 'reference mass', 6: 'births', 12: 'births'})

    def test_the_guard_counts_the_steps_since_declaration(self):
        """P1-SHOULD-1: one state at step 20, issued as declared at step 20 (k = 0) and at step 0 (k = 20), with
        densities 12 eps high, between bound(0) and bound(20): P1 and P2 refuse at k = 0 and issue at k = 20."""
        state = self.state
        for k in range(20):
            state = X.stepped(state, T.Motion(k, k+1, {p: F.IDENTITY for p in state.network.plate_ids})).state
        records = tuple(dense(c.cohort_id, 12) for c in state.material.cohorts)
        recent = undeclared(state, records, declared_step=20)
        for function in (self.p1, self.p2):
            with self.assertRaises(P.PortRefused) as caught:
                function(recent, state)
            self.assertEqual(caught.exception.detail, 'reference mass')
        early = undeclared(state, records, declared_step=0)
        self.p1(early, state)
        self.p2(early, state)

    def test_the_guard_holds_per_piece_on_a_mixed_face(self):
        """P1-NOTE-2: on an fv-cell-mean face each piece is still guarded; a second piece whose density is 30 eps
        high (issued without the declaration's checks) refuses the face's column."""
        from test_i05_transport import merged_face, remesh
        network = F.three_plates()
        cohort_of = {'s00-b01': 'one-C', 's00-b02': 'two-C'}
        state = X.crust(network, cohort_of=lambda f: cohort_of.get(f, 'inherited-'+network.face_plate(f)))
        records = tuple(dense('two-C', 30) if c.cohort_id == 'two-C' else X.record(c.cohort_id)
                        for c in state.material.cohorts)
        moving = undeclared(state, records)
        step = X.stepped(state, remesh(state, ('s00-b01', 's00-b02'), (merged_face(),)))
        after = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state
        with self.assertRaises(P.PortRefused) as caught:
            self.p1(after, step.state)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.INCOMPATIBLE_SUPPORT, 'reference mass'))

    def test_an_all_none_representation_is_the_plain_record(self):
        """P1-NOTE-3: an all-None representation is normalised to None, so one value has one port identity."""
        columns = self.p1()
        again = P.columns_port(columns.header, columns.offsets, columns.thickness_m, columns.reference_density_kg_m3,
                               columns.alpha_per_k, columns.bottom_temperature_k, columns.top_temperature_k,
                               sources=columns.sources, representation=(None,)*columns.points)
        self.assertIsNone(again.representation)
        self.assertEqual(again.port_id, columns.port_id)

    def test_the_header_names_the_moving_state_it_is_computed_from(self):
        """P1 and P2 are issued with parameter_id the moving state's moving_id (P2 amendment; I05 1.3)."""
        other = X.moving(self.state, top=600., bottom=600., base=600.)
        support = P.trace_support(self.network)
        header = port_header('P1', other, self.state, support.support_id)
        with self.assertRaises(P.PortRefused) as caught:
            R.moving_columns(self.moving, self.state, support, header, F4.datum())
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'parameter_id'))
        header = port_header('P2', other, self.state, R.piece_support_id(self.state))
        with self.assertRaises(P.PortRefused) as caught:
            R.strength_port(self.moving, self.state, header, F4.datum(), healing_law_id=R.HEALING_NONE)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'parameter_id'))


if __name__ == '__main__':
    unittest.main()
