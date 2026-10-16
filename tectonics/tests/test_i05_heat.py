"""I05.2 heat on the moving I03 support (tectonics/docs/I05_MOVING_STATE.md, rulings I05-4 to I05-6 and I05-11).

Advection is the step's own rows; vertical conduction is the column heat solve's exact modal ETD2 per piece; lateral
conduction is explicit over admitted contacts only (mode 'solve') or omitted under a passing MC-06 certificate on
fixed geometry (mode 'omit'). The worlds are the I03 control worlds with the authored test inputs of i05_fixtures.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np
from scipy.linalg import expm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F                                    # noqa: E402
import i05_fixtures as X                                    # noqa: E402

from atlas_tectonics import _integration_heat as K          # noqa: E402
from atlas_tectonics import integration_material as M      # noqa: E402
from atlas_tectonics import integration_sphere as S        # noqa: E402
from atlas_tectonics import integration_thermal as H       # noqa: E402
from atlas_tectonics import integration_transfer as T      # noqa: E402
from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters   # noqa: E402
from atlas_tectonics.plate_cooling import plate_cooling_heat                       # noqa: E402

RELATIVE = F.tolerance('relative')


def still(network, step=0, rotation=None):
    return T.Motion(step, step+1, {p: rotation or F.IDENTITY for p in network.plate_ids})


def warm_cold(network, is_warm=lambda f: F.sector_of(f) < 3, **records):
    state = X.crust(network, cohort_of=lambda f: 'warm' if is_warm(f) else 'cold')
    defaults = dict(warm=dict(top=X.T_SURFACE, bottom=X.T_BASE+200, base=None), cold=dict(base=None))
    for name, values in records.items():
        defaults[name] = values
    moving = M.declare_moving(state, (X.record('warm', **defaults['warm']), X.record('cold', **defaults['cold'])),
                              enthalpy_reference_k=X.T_REF)
    return state, moving


def certificate(state, moving, passing=True, duration=X.MYR):
    """An authored MC-06 declaration over the whole interval on the state's own cells and contacts (test input)."""
    return X.omission_certificate(state, moving, duration, allowance=1 if passing else 1e-9)


def merged_bands(network):
    """Bands 1 and 2 of every sector merged into one face: neighbouring merged faces share two edges."""
    plates = {F.sector_of(face.face_id): face.plate_id for face in network.faces}

    def merged(sector):
        k = (sector+1) % 6
        return S.Face('s%02d-merged' % sector, plates[sector], (F.vertex(sector, 1), F.vertex(k, 1), F.vertex(k, 2),
                                                                 F.vertex(k, 3), F.vertex(sector, 3),
                                                                 F.vertex(sector, 2)))
    return (tuple('s%02d-b0%d' % (i, j) for i in range(6) for j in (1, 2)), tuple(merged(i) for i in range(6)))


def merged_nodes(network, latitude):
    """X.nodes for the unmerged faces, and each merged face's node on its sector's middle meridian at ``latitude``."""
    nodes = X.nodes(network, skip=tuple(f for f in network.face_ids if f.endswith('merged')))
    return nodes+tuple((face, F.direction(60.*F.sector_of(face)+30., latitude)) for face in network.face_ids
                       if face.endswith('merged'))


def small_world(radius=20000.):
    """Three sectors and two bands (six faces) on a small sphere, where lateral and vertical conduction compare;
    each node on its sector's middle meridian at +-45 degrees."""
    network = F.sector_world((0., 120., 240.), (0.,), plates=('A', 'B', 'C'), sphere=F.sphere(radius=radius))
    return network, tuple((face, F.direction(120.*F.sector_of(face)+60., -45. if face.endswith('south') else 45.))
                          for face in network.face_ids)


def small_hot_cold(radius=20000.):
    """The small world with a uniformly hot sector beside sectors at their steady 273.15 K, all bases insulated."""
    network, nodes = small_world(radius)
    state = X.crust(network, cohort_of=lambda f: 'hot' if F.sector_of(f) == 0 else 'cold')
    hot = X.T_SURFACE+100.
    moving = M.declare_moving(state, (X.record('hot', top=hot, bottom=hot, base=None),
                                      X.record('cold', top=X.T_SURFACE, bottom=X.T_SURFACE, base=None)),
                              enthalpy_reference_k=X.T_REF)
    return network, nodes, state, moving


def column_system(record, piece, phases):
    """(A, b, C) of one column, assembled here independently: C dT/dt = A T + b with series interface conductances,
    the surface held at its temperature over a half sublayer, and the base fixed likewise or insulated."""
    t, capacity = H.column_of(record, piece, phases)
    k = [s.conductivity_w_m_k for s in record.sublayers]
    n, area = len(t), piece.area_m2
    A, b = np.zeros((n, n)), np.zeros(n)
    for i in range(n-1):
        g = area/((t[i]/2)/k[i]+(t[i+1]/2)/k[i+1])
        A[i, i] -= g
        A[i+1, i+1] -= g
        A[i, i+1] += g
        A[i+1, i] += g
    g_top = area*k[0]/(t[0]/2)
    A[0, 0] -= g_top
    b[0] += g_top*record.surface_temperature_k
    if record.base_temperature_k is not None:
        g_base = area*k[-1]/(t[-1]/2)
        A[-1, -1] -= g_base
        b[-1] += g_base*record.base_temperature_k
    return A, b, np.asarray(capacity)


def independent_lie(base=None, cp_cold=1400., k_cold=2.5):
    """(the code's temperatures after one substep, the same substep reproduced independently in the Lie order, and in
    the reverse order) on the small world with warm and cold cohorts."""
    network, nodes = small_world()
    state = X.crust(network, cohort_of=lambda f: 'warm' if F.sector_of(f) == 0 else 'cold')
    moving = M.declare_moving(state, (X.record('warm', top=X.T_SURFACE, bottom=X.T_BASE+200, base=base),
                                      X.record('cold', base=base, cp=cp_cold, k=k_cold)), enthalpy_reference_k=X.T_REF)
    step = X.stepped(state, still(network))
    conduction = M.Conduction('solve', nodes)
    out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=conduction)).state
    pieces = state.material.pieces()
    got = np.concatenate([X.column_temperatures(out, step.state, i) for i in range(len(pieces))])
    start = np.concatenate([X.column_temperatures(moving, state, i) for i in range(len(pieces))])
    records = {c.cohort_id: c for c in moving.cohorts}
    systems = [column_system(records[p.cohort_id], p, state.material.phases) for p in pieces]
    offsets = np.concatenate([[0], np.cumsum([len(s[2]) for s in systems])])
    capacity = np.concatenate([s[2] for s in systems])
    contacts = H._contacts(state, records, conduction)

    def lateral(T):
        q = np.zeros_like(T)
        for i, j, conductances in contacts:
            for l, g in enumerate(conductances):
                p, r = offsets[i]+l, offsets[j]+l
                q[p] += g*(T[r]-T[p])
                q[r] -= g*(T[r]-T[p])
        return T+X.MYR*q/capacity

    def vertical(T):
        out = []
        for k, (A, b, C) in enumerate(systems):
            n = len(C)
            system = np.zeros((n+1, n+1))
            system[:n, :n], system[:n, n] = A/C[:, None], b/C
            out.append((expm(system*X.MYR)@np.concatenate([T[offsets[k]:offsets[k+1]], [1.]]))[:n])
        return np.concatenate(out)
    return got, vertical(lateral(start)), lateral(vertical(start))


def r2_conductances(sphere, moving_state, nodes):
    """{(face, face): [G_l]} computed here from the R-2 formula alone: the faces' shared ring edges, the shared
    boundary's pole and summed arc, each node's distance R asin|n.s| to it, and per sublayer
    G_l = R theta t_l / (d_i/k_i,l + d_j/k_j,l), with t_l the thinner side's sublayer thickness."""
    network = sphere.network
    direction = dict(zip(network.vertex_ids, np.asarray(network.vertex_direction)))
    radius = network.sphere.radius_m
    rings = {}
    for face in network.faces:
        rings[face.face_id] = [(a, b) for ring in (face.vertex_ids,)+tuple(face.holes)
                               for a, b in zip(ring, ring[1:]+ring[:1])]
    pieces = {p.face_id: p for p in sphere.material.pieces()}
    unit = {f: np.asarray(d)/np.linalg.norm(d) for f, d in nodes}
    out = {}
    for left in sorted(rings):
        for right in sorted(rings):
            if not left < right:
                continue
            other = set(rings[right])
            edges = [(a, b) for a, b in rings[left] if (b, a) in other]
            if not edges:
                continue
            normal = np.cross(direction[edges[0][0]], direction[edges[0][1]])
            normal /= np.linalg.norm(normal)
            theta = math.fsum(math.atan2(np.linalg.norm(np.cross(direction[a], direction[b])),
                                         float(np.dot(direction[a], direction[b]))) for a, b in edges)
            pi, pj = pieces[left], pieces[right]
            ri, rj = moving_state.cohort(pi.cohort_id), moving_state.cohort(pj.cohort_id)
            ti = H.column_of(ri, pi, sphere.material.phases)[0]
            tj = H.column_of(rj, pj, sphere.material.phases)[0]
            di, dj = (radius*math.asin(min(1., abs(float(np.dot(normal, unit[f]))))) for f in (left, right))
            out[left, right] = [radius*theta*min(a, b)/(di/si.conductivity_w_m_k+dj/sj.conductivity_w_m_k)
                                for a, b, si, sj in zip(ti, tj, ri.sublayers, rj.sublayers)]
    return out


def owner_piece(sphere, moving_state, cell):
    """The piece whose sublayer is cell ``cell`` (cells run over pieces in I03 order, sublayers top down)."""
    for piece in sphere.material.pieces():
        size = len(moving_state.cohort(piece.cohort_id).sublayers)
        if cell < size:
            return piece
        cell -= size
    raise IndexError(cell)


def hand_contacts(sphere, moving_state):
    """The lateral contact cell pairs enumerated by hand: faces adjacent through a reversed ring edge, or one face;
    every pair of their pieces; every pair of sublayers whose depth spans overlap beyond I03's relative tolerance."""
    pieces = sphere.material.pieces()
    spans, offsets = [], [0]
    for piece in pieces:
        t, _ = H.column_of(moving_state.cohort(piece.cohort_id), piece, sphere.material.phases)
        edges = np.concatenate([[0.], np.cumsum(t)])
        spans.append(list(zip(edges[:-1], edges[1:])))
        offsets.append(offsets[-1]+len(t))
    rings = {}
    for face in sphere.network.faces:
        directed = set()
        for ring in (face.vertex_ids,)+tuple(face.holes):
            directed.update(zip(ring, ring[1:]+ring[:1]))
        rings[face.face_id] = directed
    out = set()
    for p in range(len(pieces)):
        for q in range(p+1, len(pieces)):
            a, b = pieces[p].face_id, pieces[q].face_id
            if a != b and not any((y, x) in rings[b] for x, y in rings[a]):
                continue
            scale = H._sphere.RELATIVE_TOLERANCE*max(spans[p][-1][1], spans[q][-1][1])
            for l, (top_p, bottom_p) in enumerate(spans[p]):
                for m, (top_q, bottom_q) in enumerate(spans[q]):
                    if min(bottom_p, bottom_q)-max(top_p, top_q) > scale:
                        out.add(tuple(sorted((offsets[p]+l, offsets[q]+m))))
    return tuple(sorted(out))


class HeatTests(unittest.TestCase):
    def test_translating_enthalpy_is_exact(self):
        """A heated plate rides rigidly: advection over the step's rows moves its heat with no change at all, about
        the world axis and about a tilted one; the temperature field does not depend on the declared reference."""
        for tilt in (None, F.Rotation.from_axis_angle((1., 0., 0.), .7)):
            network = F.sector_world(tilt=tilt)
            state = X.crust(network)
            records = tuple(X.record(c.cohort_id, top=800. if c.cohort_id == 'inherited-A' else X.T_SURFACE)
                            for c in state.material.cohorts)
            moving = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF)
            step = X.stepped(state, still(network, rotation=F.spin(7., tilt)))
            after = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state
            self.assertEqual(after.arrays()['moving.heat_j'].tobytes(), moving.arrays()['moving.heat_j'].tobytes())
        shifted = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF+150.)
        for i in range(len(state.material.pieces())):
            a = X.column_temperatures(moving, state, i)
            b = X.column_temperatures(shifted, state, i)
            np.testing.assert_allclose(a, b, rtol=RELATIVE, atol=0)

    def test_stationary_column_stays_unchanged_and_accounts_close(self):
        network = F.sector_world()
        state = X.crust(network)
        moving = X.moving(state)                                   # linear, steady: fixed 273.15 K and 573.15 K
        step = X.stepped(state, still(network))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'solve', X.nodes(network)))).state
        for i in range(len(out.pieces)):
            np.testing.assert_allclose(X.column_temperatures(out, step.state, i),
                                       X.column_temperatures(moving, state, i), rtol=RELATIVE, atol=0)
        self.assertTrue(out.closure()['identity_exact'])

    def test_series_resistance_conductance_and_lateral_exchange(self):
        """Across an admitted contact G = A/(d_i/k_i + d_j/k_j), never an average of k; lateral heat leaves one
        column exactly as it enters the other."""
        network = F.sector_world()
        state, moving = warm_cold(network, cold=dict(base=None, k=1.5))
        conduction = M.Conduction('solve', X.nodes(network))
        records = {c.cohort_id: c for c in moving.cohorts}
        contacts = H._contacts(state, records, conduction)
        faces = state.network.face_ids
        pieces = state.material.pieces()
        nodes = dict(conduction.nodes)
        checked = 0
        for i, j, conductances in contacts:
            a, b = pieces[i], pieces[j]
            if a.cohort_id == b.cohort_id:
                continue
            (edge,) = H._edges(network)[tuple(sorted((a.face_id, b.face_id)))]
            direction = dict(zip(network.vertex_ids, np.asarray(network.vertex_direction)))
            va, vb = direction[edge[0]], direction[edge[1]]
            normal = np.cross(va, vb)/np.linalg.norm(np.cross(va, vb))
            radius = network.sphere.radius_m
            d = [radius*math.asin(abs(float(np.dot(normal, np.asarray(nodes[p.face_id])/np.linalg.norm(
                nodes[p.face_id]))))) for p in (a, b)]
            k = [records[p.cohort_id].sublayers[0].conductivity_w_m_k for p in (a, b)]
            theta = math.atan2(np.linalg.norm(np.cross(va, vb)), float(np.dot(va, vb)))
            t = H.column_of(records[a.cohort_id], a, state.material.phases)[0][0]
            self.assertAlmostEqual(conductances[0], radius*theta*t/(d[0]/k[0]+d[1]/k[1]), delta=RELATIVE*conductances[0])
            self.assertNotAlmostEqual(conductances[0], radius*theta*t*((k[0]+k[1])/2)/(d[0]+d[1]),
                                      delta=1e-6*conductances[0])
            checked += 1
            del faces
            faces = state.network.face_ids
        self.assertGreater(checked, 0)
        step = X.stepped(state, still(network))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=conduction))
        report = out.summary['conduction']
        self.assertLessEqual(abs(report['lateral_net_j']), 1e-12*report['surface_out_j'])
        self.assertLessEqual(report['closure_relative'], H.ALGEBRA_RELATIVE)

    def test_split_scheme_converges_to_the_coupled_solution(self):
        """On a small sphere where lateral and vertical conduction are comparable, the explicit lateral scheme
        approaches the exact solution of the same coupled semi-discrete system as substeps increase (Lie splitting,
        first order: the decrease is reported, no new order criterion is set here)."""
        network = F.sector_world((0., 120., 240.), (0.,), plates=('A', 'B', 'C'), sphere=F.sphere(radius=20000.))
        state, moving = warm_cold(network, is_warm=lambda f: F.sector_of(f) == 0, cold=dict(base=None, cp=1400.))
        nodes = []
        for face in network.face_ids:
            lon = 120.*F.sector_of(face)+60.
            nodes.append((face, F.direction(lon, -45. if face.endswith('south') else 45.)))
        step = X.stepped(state, still(network))
        records = {c.cohort_id: c for c in moving.cohorts}
        pieces = state.material.pieces()
        phases = state.material.phases
        sizes = [len(records[p.cohort_id].sublayers) for p in pieces]
        offsets = np.concatenate([[0], np.cumsum(sizes)])
        n = offsets[-1]
        A, b, C = np.zeros((n, n)), np.zeros(n), np.zeros(n)
        for k, p in enumerate(pieces):
            record = records[p.cohort_id]
            thickness, capacity = H.column_of(record, p, phases)
            thermal, _ = H._prepared(record, thickness, X.MYR, {})
            s = slice(offsets[k], offsets[k+1])
            A[s, s] -= thermal.operator()*p.area_m2
            b[offsets[k]] += thermal.boundary_conductance[0]*record.surface_temperature_k*p.area_m2
            C[s] = capacity
        for i, j, conductances in H._contacts(state, records, M.Conduction('solve', tuple(nodes))):
            for l, g in enumerate(conductances):
                p, q = offsets[i]+l, offsets[j]+l
                A[p, p] -= g
                A[q, q] -= g
                A[p, q] += g
                A[q, p] += g
        system = np.zeros((n+1, n+1))
        system[:n, :n], system[:n, n] = A/C[:, None], b/C
        start = np.concatenate([X.column_temperatures(moving, state, k) for k in range(len(pieces))]+[[1.]])
        exact = (expm(system*X.MYR)@start)[:n]
        errors = []
        for substeps in (1, 2, 4, 8, 16):
            out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'solve', tuple(nodes), substeps=substeps))).state
            got = np.concatenate([X.column_temperatures(out, step.state, k) for k in range(len(pieces))])
            errors.append(float(np.max(np.abs(got-exact))))
            self.assertTrue(out.closure()['identity_exact'])
        self.assertEqual(errors, sorted(errors, reverse=True))
        self.assertLess(errors[-1], errors[0])
        # Over 100 intervals' time in one step the explicit lateral update is unstable unless enough substeps are
        # declared: it refuses, never substeps on its own.
        long = T.advance(state, still(network), end_time_s=state.network.time_s+100*X.MYR)
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moving, state, long, M.MovingAdvance(0, 1, conduction=M.Conduction('solve', tuple(nodes))))
        self.assertEqual(caught.exception.detail, 'stability')
        stable = M.advance_moving(moving, state, long, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'solve', tuple(nodes), substeps=64)))
        self.assertLessEqual(stable.summary['conduction']['stability'], H.STABILITY)

    def test_heterogeneous_capacity_exchanges_heat_with_exact_closure(self):
        """Cohorts of different constant cp (the admitted 'variable capacity': H(T) = cp (T - T_ref) per material)
        exchange heat laterally; the caloric inverse gives their temperatures and energy closes."""
        network = F.sector_world()
        state, moving = warm_cold(network, warm=dict(top=X.T_SURFACE, bottom=X.T_BASE+200, base=None, cp=800.),
                                  cold=dict(base=None, cp=1300.))
        step = X.stepped(state, still(network))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'solve', X.nodes(network), substeps=2)))
        self.assertTrue(out.state.closure()['identity_exact'])
        report = out.summary['conduction']
        self.assertLessEqual(report['closure_relative'], H.ALGEBRA_RELATIVE)
        change = X.total_heat(out.state)-X.total_heat(moving)
        expected = -report['surface_out_j']+report['base_in_j']+report['radiogenic_j']+report['lateral_net_j']
        self.assertLessEqual(abs(change-expected), H.ALGEBRA_RELATIVE*abs(report['surface_out_j']))
        sublayer = moving.cohort('warm').sublayers[0]
        self.assertEqual(sublayer.temperature(sublayer.caloric(1000., X.T_REF), X.T_REF), 1000.)

    def test_two_age_occupied_ocean_mixture_is_the_age_integral(self):
        """The occupied mean of two pieces at their own ages is the exact age-distribution integral; cooling the
        mixture at its mean age is refused (W06; CM-02). Half-space branch of W03's plate (Fo <= 1/576)."""
        k, kappa, dT = 3.3, 1e-6, 1300.
        plate = PlateCoolingParameters(ThermalParameters('test:plate', 'test: authored', 273., 273.+dT, kappa),
                                       100e3, k)
        t = 1e13
        q0, qt = (float(plate_cooling_heat(np.array([age]), plate)[0, 0]) for age in (0., t))
        exact = 2*k*dT*math.sqrt(t/(math.pi*kappa))
        self.assertEqual(q0, 0.)
        self.assertLessEqual(abs(qt-exact), 1e-12*exact)
        area = 1.5e10
        mixture = H.occupied_mean([(q0, area), (qt, area)])
        self.assertLessEqual(abs(mixture-exact/2), 1e-12*exact)
        mean_age = float(plate_cooling_heat(np.array([t/2]), plate)[0, 0])
        self.assertLessEqual(abs(mixture/mean_age-1/math.sqrt(2)), 1e-12)
        self.assertIsNone(H.occupied_mean([]))
        self.assertIsNone(H.occupied_mean([(5., 0.)]))
        with self.assertRaises(H.ThermalRefused):
            H.mean_age_cooling((0., t))

    def test_face_mean_uses_occupied_oceanic_pieces_only(self):
        network = F.three_plates()
        cohort_of = {'s00-b01': 'ocean-young', 's00-b02': 'ocean-old'}
        state = X.crust(network, cohort_of=lambda f: cohort_of.get(f, 'continent'))
        records = (X.record('continent'), X.record('ocean-young', top=500., bottom=900.), X.record('ocean-old'))
        moving = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF)
        from test_i05_transport import merged_face, remesh
        step = X.stepped(state, remesh(state, ('s00-b01', 's00-b02'), (merged_face(),)))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state
        oceanic = lambda record: record.cohort_id.startswith('ocean')

        def top(record, piece, heat):
            return H.temperatures(record, piece, heat, X.T_REF, step.state.material.phases)[0]
        rows = [(top(out.cohort(p.cohort_id), p, out.heat_j(i).tolist()), p.area_m2)
                for i, p in enumerate(step.state.material.pieces()) if p.face_id == 's00-merged']
        self.assertEqual(len(rows), 2)
        self.assertEqual(H.face_mean(out, step.state, 's00-merged', top, occupied=oceanic), H.occupied_mean(rows))
        self.assertIsNone(H.face_mean(out, step.state, 's01-b01', top, occupied=oceanic))

    def test_unsupported_contacts_and_geometry_refuse(self):
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        nodes = dict(X.nodes(network))
        latitude = math.degrees(math.asin(nodes['s00-b01'][2]))       # inside its face, off its sector's meridian
        bent = dict(nodes, **{'s00-b01': F.direction(31., latitude)})
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'solve', tuple(bent.items()))))
        self.assertEqual(caught.exception.code, H.NONORTHOGONAL)
        missing = {f: d for f, d in nodes.items() if f != 's03-b00'}
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'solve', tuple(missing.items()))))
        self.assertEqual(caught.exception.code, H.UNRESOLVED_CONTACT)
        # A face holding two cohort pieces: which one touches the edge is not represented.
        from test_i05_transport import merged_face, remesh
        mixed_state, mixed_moving = warm_cold(network, is_warm=lambda f: F.sector_of(f) < 3 and f != 's02-b02')
        merged = X.stepped(mixed_state, remesh(mixed_state, ('s02-b01', 's02-b02'), (merged_face(2, 'B'),)))
        moved = M.advance_moving(mixed_moving, mixed_state, merged, M.MovingAdvance(0, 1))
        self.assertEqual(merged.state.material.face_cohorts('s02-merged'), ('cold', 'warm'))
        nodes2 = dict(X.nodes(merged.state.network, skip=('s02-merged',)))
        nodes2['s02-merged'] = F.direction(150., 0.)
        mixed = X.stepped(merged.state, still(merged.state.network, 1))
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moved.state, merged.state, mixed, M.MovingAdvance(1, 2, conduction=M.Conduction(
                'solve', tuple(nodes2.items()))))
        self.assertEqual(caught.exception.code, H.UNRESOLVED_CONTACT)      # checked before any node of the pair
        # Omission needs a passing certificate and fixed contact geometry.
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'omit', X.nodes(network), certificate=certificate(state, moving))))
        self.assertEqual(out.summary['conduction']['certificate']['status'], 'PASS_CONDITIONAL_THERMAL_BOUND')
        for bad in (certificate(state, moving, False), certificate(state, moving, duration=X.MYR/2)):
            with self.assertRaises(H.ThermalRefused):
                M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                    'omit', X.nodes(network), certificate=bad)))
        moving_world = F.three_plates()
        plates = X.crust(moving_world)
        turning = X.stepped(plates, X.motion())
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(X.moving(plates), plates, turning, X.advance(conduction=M.Conduction(
                'omit', X.nodes(moving_world), certificate=certificate(plates, X.moving(plates)))))
        self.assertEqual(caught.exception.detail, 'omit')
        with self.assertRaises(H.ThermalRefused) as caught:    # the born ridge faces declare no node
            M.advance_moving(X.moving(plates), plates, turning, X.advance(conduction=M.Conduction(
                'solve', X.nodes(moving_world))))
        self.assertEqual(caught.exception.code, H.UNRESOLVED_CONTACT)


class HeatRepairs(unittest.TestCase):
    """The repairs of the I05a verification: the lateral exchange keeps the maximum principle, a shared boundary of
    several edges conducts whole, an omission certificate is the state's own network with a carried error bound, and
    nodes and means check what they are given."""

    def test_lateral_exchange_keeps_the_maximum_principle(self):
        """A hot column beside columns at their steady 273.15 K, all with insulated bases: at an admitted explicit
        ratio of 0.89 no temperature leaves the range of the starting and boundary values (W07's check)."""
        hot = X.T_SURFACE+100.

        def run(radius):
            network = F.sector_world((0., 120., 240.), (0.,), plates=('A', 'B', 'C'), sphere=F.sphere(radius=radius))
            nodes = tuple((face, F.direction(120.*F.sector_of(face)+60., -45. if face.endswith('south') else 45.))
                          for face in network.face_ids)
            state = X.crust(network, cohort_of=lambda f: 'hot' if F.sector_of(f) == 0 else 'cold')
            moving = M.declare_moving(state, (X.record('hot', top=hot, bottom=hot, base=None),
                                              X.record('cold', top=X.T_SURFACE, bottom=X.T_SURFACE, base=None)),
                                      enthalpy_reference_k=X.T_REF)
            step = X.stepped(state, still(network))
            out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction('solve', nodes)))
            return out, np.concatenate([X.column_temperatures(out.state, step.state, k)
                                        for k in range(len(state.material.pieces()))])
        out, _ = run(20000.)
        out, temperature = run(20000.*math.sqrt(out.summary['conduction']['stability']/.89))
        self.assertAlmostEqual(out.summary['conduction']['stability'], .89, delta=1e-9)
        tolerance = 128*np.finfo(float).eps*hot
        self.assertGreaterEqual(float(temperature.min()), X.T_SURFACE-tolerance)
        self.assertLessEqual(float(temperature.max()), hot+tolerance)
        self.assertTrue(out.state.closure()['identity_exact'])

    def test_faces_sharing_several_edges_conduct_over_their_whole_shared_boundary(self):
        network = F.sector_world()
        state, moving = warm_cold(network, cold=dict(base=None, k=1.5))
        from test_i05_transport import remesh
        step = X.stepped(state, remesh(state, *merged_bands(network)))
        end = step.state.network
        pair = ('s00-merged', 's01-merged')
        edges = H._edges(end)[pair]
        self.assertEqual(len(edges), 2)
        direction = dict(zip(end.vertex_ids, np.asarray(end.vertex_direction)))

        def angle(a, b):
            return math.atan2(np.linalg.norm(np.cross(direction[a], direction[b])), float(np.dot(direction[a],
                                                                                                  direction[b])))
        total = sum(angle(a, b) for a, b in edges)
        normal = np.cross(direction[edges[0][0]], direction[edges[0][1]])
        normal /= np.linalg.norm(normal)
        records = {c.cohort_id: c for c in moving.cohorts}
        pieces = step.state.material.pieces()
        radius = end.sphere.radius_m
        for latitude in (0., 10., -10.):                       # crossing on either shared edge is admitted
            nodes = merged_nodes(end, latitude)
            conduction = M.Conduction('solve', nodes)
            out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=conduction))
            self.assertTrue(out.state.closure()['identity_exact'])
            (g,) = [g for i, j, g in H._contacts(step.state, records, conduction)
                    if {pieces[i].face_id, pieces[j].face_id} == set(pair)]
            node = dict(conduction.nodes)
            d = [radius*math.asin(abs(float(np.dot(normal, np.asarray(node[f])/np.linalg.norm(node[f])))))
                 for f in pair]
            source = [p for p in pieces if p.face_id in pair]
            k = [records[p.cohort_id].sublayers[0].conductivity_w_m_k for p in source]
            t = min(H.column_of(records[p.cohort_id], p, step.state.material.phases)[0][0] for p in source)
            expected = radius*total*t/(d[0]/k[0]+d[1]/k[1])
            self.assertLessEqual(abs(g[0]-expected), 1e-12*expected, latitude)

    def test_omission_certificate_is_the_states_own_network(self):
        """MC-06 runs on this state's own cells and the R-2 conductances of its admitted contacts, derived from the
        declared k and nodes (ruling (c)); a certificate declares only windows and allowance. Declared cells or
        conductances, missing nodes, a mis-sized envelope or a reset initial bound refuse."""
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        records = {c.cohort_id: c for c in moving.cohorts}
        nodes = X.nodes(network)
        full = X.omission_certificate(state, moving, X.MYR)
        capacities, contacts = H.omission_cells(state, records)
        admitted = H._contacts(state, records, M.Conduction('solve', nodes))
        lateral, order = H._omission_network(state, records, admitted)
        self.assertEqual(order, contacts)
        self.assertEqual(lateral.capacities, tuple(Fraction(c) for c in capacities))
        offsets = np.concatenate([[0], np.cumsum([len(records[p.cohort_id].sublayers)
                                                  for p in state.material.pieces()])])
        derived = {tuple(sorted((offsets[i]+l, offsets[j]+l))): Fraction(g) for i, j, gs in admitted
                   for l, g in enumerate(gs)}
        self.assertEqual({(i, j): g for i, j, g in lateral.contacts}, derived)    # the solve's own G, exactly
        window = full['windows'][0]
        declared = dict(full, capacities_j_k=[10**20], contacts=[])
        missized = dict(full, windows=[dict(window, envelope=dict(window['envelope'],
                                                                  difference_bounds_k=[500]*(len(contacts)-1)))])
        for conduction in (M.Conduction('omit', nodes, certificate=declared),
                           M.Conduction('omit', nodes, certificate=missized),
                           M.Conduction('omit', nodes, certificate=dict(full, initial_error_bound_k=.5))):
            with self.assertRaises(H.ThermalRefused) as caught:
                M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=conduction))
            self.assertEqual(caught.exception.detail, 'certificate')
        with self.assertRaises(H.ThermalRefused) as caught:                # conductances need the declared nodes
            M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'omit', certificate=full)))
        self.assertEqual(caught.exception.code, H.UNRESOLVED_CONTACT)
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'omit', nodes, certificate=full)))
        report = out.summary['conduction']['certificate']
        self.assertEqual((report['status'], report['cells'], report['contacts']),
                         ('PASS_CONDITIONAL_THERMAL_BOUND', len(capacities), len(contacts)))

    def test_an_envelope_the_states_own_temperatures_refute_is_refused(self):
        """heat-1: the start and end temperatures of the column-only trajectory are samples of what the envelope must
        bound; an envelope below a sampled difference is refused at the start or at the end."""
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        nodes = X.nodes(network)
        records = {c.cohort_id: c for c in moving.cohorts}
        _, order = H.omission_cells(state, records)
        start = np.concatenate([X.column_temperatures(moving, state, k) for k in range(len(state.material.pieces()))])
        valid = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'omit', nodes, certificate=X.omission_certificate(state, moving, X.MYR))))
        end = np.concatenate([X.column_temperatures(valid.state, step.state, k)
                              for k in range(len(state.material.pieces()))])
        begin = [float(abs(start[a]-start[b])) for a, b in order]
        finish = [float(abs(end[a]-end[b])) for a, b in order]

        def with_bounds(bounds):
            certificate = X.omission_certificate(state, moving, X.MYR)
            window = certificate['windows'][0]
            return M.Conduction('omit', nodes, certificate=dict(certificate, windows=[
                dict(window, envelope=dict(window['envelope'], difference_bounds_k=bounds))]))
        largest = int(np.argmax(begin))
        low = [max(a, b) for a, b in zip(begin, finish)]
        low[largest] = math.nextafter(begin[largest], 0.)
        grows = [c for c in range(len(order)) if finish[c] > begin[c]]
        self.assertTrue(grows)
        late = [max(a, b) for a, b in zip(begin, finish)]
        late[grows[0]] = begin[grows[0]]
        for bounds, when in ((low, 'start'), (late, 'end'), ([0.]*len(order), 'start')):
            with self.assertRaises(H.ThermalRefused) as caught:
                M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=with_bounds(bounds)))
            self.assertEqual(caught.exception.detail, 'certificate')
            self.assertIn('at the window '+when, str(caught.exception))
        M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=with_bounds(
            [max(a, b) for a, b in zip(begin, finish)])))                  # the sampled differences themselves pass

    def test_omission_error_bound_is_carried_across_intervals(self):
        """A continuation carries the previous window's bound (I01_LATERAL_HEAT), never resets it: two windows that
        each pass alone refuse together, a solved interval keeps the bound and a restore reproduces it."""
        network = F.sector_world()
        state, moving = warm_cold(network)

        def omit(sphere, parent, allowance):
            return M.Conduction('omit', X.nodes(network), certificate=X.omission_certificate(
                sphere, parent, X.MYR, allowance=allowance))
        step = X.stepped(state, still(network))
        first = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=omit(state, moving, 1)))
        bound = Fraction(first.summary['conduction']['certificate']['error_bound_exact_k'])
        self.assertGreater(bound, 0)
        carried = Fraction(first.state.descriptor()['lateral_omission_error_k'])     # rounded up to binary64
        self.assertTrue(bound <= carried <= bound*(1+Fraction(1, 2**52)))
        self.assertEqual(carried, Fraction(float(carried)))
        self.assertEqual(Fraction(moving.descriptor()['lateral_omission_error_k']), 0)
        later = X.stepped(step.state, still(step.state.network, 1))
        probe = M.advance_moving(first.state, step.state, later, M.MovingAdvance(1, 2, conduction=omit(
            step.state, first.state, 10**9)))
        increment = Fraction(probe.summary['conduction']['certificate']['increments_exact_k'][0])
        self.assertEqual(Fraction(probe.summary['conduction']['certificate']['error_bound_exact_k']),
                         carried+increment)
        alone = float(increment+carried/2)                         # enough for this window alone, not for the chain
        self.assertTrue(increment <= Fraction(alone) < carried+increment)
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(first.state, step.state, later, M.MovingAdvance(1, 2, conduction=omit(
                step.state, first.state, alone)))
        self.assertEqual(caught.exception.detail, 'certificate')
        solved = M.advance_moving(first.state, step.state, later, M.MovingAdvance(1, 2, conduction=M.Conduction(
            'solve', X.nodes(network))))
        self.assertEqual(Fraction(solved.state.descriptor()['lateral_omission_error_k']), carried)
        again = M.restore_moving(probe.state.descriptor(), probe.state.arrays(), later.state)
        self.assertEqual(again.moving_id, probe.state.moving_id)

    def test_an_interval_without_conduction_makes_the_carried_bound_unknown(self):
        """heat-2: advection only leaves the column-only trajectory, so the carried bound becomes UNKNOWN; a later
        omission refuses to chain from it, a solved interval keeps it UNKNOWN, and a restore reproduces it."""
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        first = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
            'omit', X.nodes(network), certificate=X.omission_certificate(state, moving, X.MYR))))
        later = X.stepped(step.state, still(step.state.network, 1))
        advected = M.advance_moving(first.state, step.state, later, M.MovingAdvance(1, 2)).state
        self.assertEqual(advected.descriptor()['lateral_omission_error_k'], M.UNKNOWN_BOUND)
        last = X.stepped(later.state, still(later.state.network, 2))
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(advected, later.state, last, M.MovingAdvance(2, 3, conduction=M.Conduction(
                'omit', X.nodes(network), certificate=X.omission_certificate(later.state, advected, X.MYR))))
        self.assertEqual(caught.exception.detail, 'certificate')
        self.assertIn('UNKNOWN', str(caught.exception))
        solved = M.advance_moving(advected, later.state, last, M.MovingAdvance(2, 3, conduction=M.Conduction(
            'solve', X.nodes(network)))).state
        self.assertEqual(solved.descriptor()['lateral_omission_error_k'], M.UNKNOWN_BOUND)
        again = M.restore_moving(advected.descriptor(), advected.arrays(), later.state)
        self.assertEqual(again.moving_id, advected.moving_id)

    def test_the_stability_limit_is_pinned_at_its_edge(self):
        """heat-3: the W07 limit 0.9, accepted to (1 + 8 eps): a ratio of 0.9(1 + 4 eps) is admitted and one of
        0.9(1 + 1e-9) refused."""
        network, nodes, state, moving = small_hot_cold()

        def attempt(duration):
            step = T.advance(state, still(network), end_time_s=state.network.time_s+duration)
            return M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction('solve',
                                                                                                    nodes)))
        ratio = attempt(X.MYR).summary['conduction']['stability']
        admitted = attempt(X.MYR*.9/ratio*(1+4*2.**-52)).summary['conduction']['stability']
        self.assertTrue(.9 < admitted <= .9*(1+8*2.**-52), admitted)
        with self.assertRaises(H.ThermalRefused) as caught:
            attempt(X.MYR*.9/ratio*(1+1e-9))
        self.assertEqual(caught.exception.detail, 'stability')
        # heat-R1-03: the reported ratio is dt max over cells of sum(G)/C, computed here independently (G from the
        # R-2 formula, C = rho cp t A), with G_bdy = 0 for the lateral operator.
        pieces = state.material.pieces()
        index = {p.face_id: i for i, p in enumerate(pieces)}
        loss = [[0.]*X.LAYERS for _ in pieces]
        for (left, right), conductances in r2_conductances(state, moving, nodes).items():
            for l, g in enumerate(conductances):
                loss[index[left]][l] += g
                loss[index[right]][l] += g
        worst = 0.
        for i, p in enumerate(pieces):
            record = moving.cohort(p.cohort_id)
            capacity = [s.reference_density_kg_m3*s.heat_capacity_j_kg_k*t*p.area_m2
                        for s, t in zip(record.sublayers, H.column_of(record, p, state.material.phases)[0])]
            worst = max(worst, max(X.MYR*g/c for g, c in zip(loss[i], capacity)))
        self.assertLessEqual(abs(ratio-worst), 1e-12*worst)

    def test_every_sublayer_conductance_is_the_r2_series_form(self):
        """heat-R1-02: a layered control (unequal sublayer thicknesses, a different k in every sublayer, different on
        the two sides) pins every conductances[l] against the R-2 formula computed in the test."""
        network = F.sector_world()
        state = X.crust(network, cohort_of=lambda f: 'warm' if F.sector_of(f) < 3 else 'cold')
        thickness = (1000., 2500., 1750., 1750.)

        def layered(cohort, ks):
            sublayers = tuple(replace(s, thickness_m=h, conductivity_w_m_k=k)
                              for s, h, k in zip(X.sublayers(), thickness, ks))
            return replace(X.record(cohort, base=None), sublayers=sublayers)
        moving = M.declare_moving(state, (layered('warm', (1., 2., 3., 4.)), layered('cold', (4.5, .5, 2.5, 1.5))),
                                  enthalpy_reference_k=X.T_REF)
        nodes = X.nodes(network)
        contacts = H._contacts(state, {c.cohort_id: c for c in moving.cohorts}, M.Conduction('solve', nodes))
        expected = r2_conductances(state, moving, nodes)
        pieces = state.material.pieces()
        self.assertEqual(len(contacts), len(expected))
        mixed = 0
        for i, j, conductances in contacts:
            want = expected[pieces[i].face_id, pieces[j].face_id]
            self.assertEqual(len(conductances), X.LAYERS)
            for got, value in zip(conductances, want):
                self.assertLessEqual(abs(got-value), 1e-12*value)
            mixed += pieces[i].cohort_id != pieces[j].cohort_id
        self.assertGreater(mixed, 0)                               # contacts across the two layered cohorts

    def test_an_omission_certificate_has_exactly_one_window(self):
        """heat-R1-01 (ruling): one window per interval, since a middle window's envelope is never sampled; a
        three-window certificate whose middle window declares 0 K envelopes is refused."""
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        full = X.omission_certificate(state, moving, X.MYR)
        window = full['windows'][0]
        _, order = H.omission_cells(state, {c.cohort_id: c for c in moving.cohorts})
        third = X.MYR/3
        windows = [dict(window, duration_s=third), dict(window, duration_s=third, envelope=dict(
            window['envelope'], difference_bounds_k=[0.]*len(order))), dict(window, duration_s=X.MYR-2*third)]
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'omit', X.nodes(network), certificate=dict(full, windows=windows))))
        self.assertEqual(caught.exception.detail, 'certificate')
        self.assertIn('exactly one window', str(caught.exception))

    def test_one_substep_is_the_lateral_exchange_then_the_exact_vertical_solve(self):
        """heat-4 and heat-5: one substep reproduced independently (forward-Euler lateral exchange with the R-2 G,
        then each column's own operator integrated by scipy's matrix exponential) to about 1e-11 relative; the reverse
        order differs by far more, so this pins both the Lie order and the size of the interface flux."""
        for options in (dict(), dict(base=X.T_BASE, cp_cold=300., k_cold=4.)):
            got, lie, reverse = independent_lie(**options)
            scale = float(np.max(np.abs(lie)))
            self.assertLessEqual(float(np.max(np.abs(got-lie))), 1e-11*scale, options)
            self.assertGreater(float(np.max(np.abs(got-reverse))), 1e-6*scale, options)

    def test_strict_contact_admission_refusals(self):
        """heat-6: different sublayer depths, a kinked shared boundary, a node line crossing outside the shared edge,
        and a node outside the 64 eps orthogonality band all refuse; a node inside the band is admitted."""
        network, nodes = small_world()
        state = X.crust(network, cohort_of=lambda f: 'warm' if F.sector_of(f) == 0 else 'cold')
        step = X.stepped(state, still(network))
        split = tuple(replace(s, thickness_m=h) for s, h in zip(X.sublayers(), (1000., 2500., 1750., 1750.)))
        cold = replace(X.record('cold', base=None), sublayers=split)
        offset = M.declare_moving(state, (X.record('warm', base=None), cold), enthalpy_reference_k=X.T_REF)
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(offset, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction('solve', nodes)))
        self.assertEqual(caught.exception.code, H.NONORTHOGONAL)
        self.assertIn('different sublayer depths', str(caught.exception))
        moving = M.declare_moving(state, (X.record('warm', base=None), X.record('cold', base=None)),
                                  enthalpy_reference_k=X.T_REF)
        crossing = dict(nodes)
        crossing.update({'s00-north': F.direction(20., 45.), 's00-south': F.direction(20., -45.),
                         's01-north': F.direction(220., 45.)})
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'solve', tuple(crossing.items()))))
        self.assertEqual(caught.exception.code, H.NONORTHOGONAL)
        self.assertIn('crosses outside', str(caught.exception))
        # A kink: an L-shaped face (s00-b02, s01-b01 and s01-b02) wraps a corner of s00-b01, sharing its meridian edge
        # and its band edge, which lie on two great circles. It is named to be checked first.
        sector = F.sector_world()
        kinked, kinked_moving = warm_cold(sector)
        from test_i05_transport import remesh
        ring = tuple(F.vertex(*corner) for corner in ((1, 1), (2, 1), (2, 2), (2, 3), (1, 3), (0, 3), (0, 2), (1, 2)))
        corner = X.stepped(kinked, remesh(kinked, ('s00-b02', 's01-b01', 's01-b02'), (S.Face('aa-kink', 'A', ring),)))
        given = dict(X.nodes(sector, skip=('s00-b02', 's01-b01', 's01-b02')), **{'aa-kink': F.direction(90., 15.)})
        with self.assertRaises(H.ThermalRefused) as caught:
            M.advance_moving(kinked_moving, kinked, corner, M.MovingAdvance(0, 1, conduction=M.Conduction(
                'solve', tuple(given.items()))))
        self.assertEqual(caught.exception.code, H.NONORTHOGONAL)
        self.assertIn('not one great-circle arc', str(caught.exception))
        # The band: turn s00-north's node about the polar axis until the worst |n.(s_i x s_j)| of its contacts is
        # 10 or 0.1 times I03's attachment band.
        records = {c.cohort_id: c for c in moving.cohorts}
        lon, lat = 60., 45.

        def deviation(delta):
            given = dict(nodes, **{'s00-north': F.direction(lon+math.degrees(delta), lat)})
            unit = {f: np.asarray(d)/np.linalg.norm(d) for f, d in given.items()}
            direction = dict(zip(network.vertex_ids, np.asarray(network.vertex_direction)))
            worst = 0.
            for (left, right), edges in H._edges(network).items():
                if 's00-north' in (left, right):
                    a, b = edges[0]
                    n = np.cross(direction[a], direction[b])
                    n /= np.linalg.norm(n)
                    worst = max(worst, abs(float(np.dot(n, np.cross(unit[left], unit[right])))))
            return given, worst
        _, unit_deviation = deviation(1e-9)
        for factor, refused in ((10., True), (.1, False)):
            given, _ = deviation(1e-9*factor*H._sphere.ATTACHMENT_BAND_RAD/unit_deviation)
            conduction = M.Conduction('solve', tuple(given.items()))
            if refused:
                with self.assertRaises(H.ThermalRefused) as caught:
                    H._contacts(state, records, conduction)
                self.assertEqual(caught.exception.code, H.NONORTHOGONAL)
            else:
                self.assertTrue(H._contacts(state, records, conduction))

    def test_omission_cells_against_hand_enumerated_contacts(self):
        """heat-7: offset sublayer depths make contacts between different sublayer indices that overlap in depth, and
        a face holding two pieces makes contacts between them; both sets are enumerated here by hand."""
        network, _ = small_world()
        state = X.crust(network, cohort_of=lambda f: 'warm' if F.sector_of(f) == 0 else 'cold')
        split = tuple(replace(s, thickness_m=h) for s, h in zip(X.sublayers(), (1000., 2500., 1750., 1750.)))
        offset = M.declare_moving(state, (X.record('warm', base=None),
                                          replace(X.record('cold', base=None), sublayers=split)),
                                  enthalpy_reference_k=X.T_REF)
        self.assertEqual(H.omission_cells(state, {c.cohort_id: c for c in offset.cohorts})[1],
                         hand_contacts(state, offset))
        three = F.three_plates()
        cohort_of = {'s00-b01': 'ocean-young', 's00-b02': 'ocean-old'}
        plates = X.crust(three, cohort_of=lambda f: cohort_of.get(f, 'continent'))
        moving = M.declare_moving(plates, (X.record('continent'), X.record('ocean-young', top=500., bottom=900.),
                                           X.record('ocean-old')), enthalpy_reference_k=X.T_REF)
        from test_i05_transport import merged_face, remesh
        step = X.stepped(plates, remesh(plates, ('s00-b01', 's00-b02'), (merged_face(),)))
        merged = M.advance_moving(moving, plates, step, M.MovingAdvance(0, 1)).state
        cells = H.omission_cells(step.state, {c.cohort_id: c for c in merged.cohorts})[1]
        expected = hand_contacts(step.state, merged)
        self.assertEqual(cells, expected)
        pieces = step.state.material.pieces()
        same_face = [(a, b) for a, b in expected if owner_piece(step.state, merged, a).face_id == 's00-merged'
                     and owner_piece(step.state, merged, b).face_id == 's00-merged']
        self.assertEqual(len(same_face), X.LAYERS)                 # the two pieces of the merged face, layer by layer
        self.assertEqual(len([p for p in pieces if p.face_id == 's00-merged']), 2)

    def test_the_occupied_mean_is_area_weighted(self):
        """heat-8: two ages {0, t} on unequal areas give a2 Q(t)/(a1 + a2); face_mean equals an independent
        area-weighted sum over the face's occupied pieces."""
        k, kappa, dT, t = 3.3, 1e-6, 1300., 1e13
        q0, qt = 0., 2*k*dT*math.sqrt(t/(math.pi*kappa))
        a1, a2 = 1.5e10, 4.5e10
        self.assertLessEqual(abs(H.occupied_mean([(q0, a1), (qt, a2)])-a2*qt/(a1+a2)), 1e-12*qt)
        network = F.three_plates()
        cohort_of = {'s00-b00': 'ocean-young', 's00-b01': 'ocean-old'}             # bands of unequal area
        state = X.crust(network, cohort_of=lambda f: cohort_of.get(f, 'continent'))
        moving = M.declare_moving(state, (X.record('continent'), X.record('ocean-young', top=500., bottom=900.),
                                          X.record('ocean-old')), enthalpy_reference_k=X.T_REF)
        from test_i05_transport import remesh
        low = S.Face('s00-merged', 'C', tuple(F.vertex(*c) for c in ((0, 0), (1, 0), (1, 1), (1, 2), (0, 2), (0, 1))))
        step = X.stepped(state, remesh(state, ('s00-b00', 's00-b01'), (low,)))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state

        def top(record, piece, heat):
            return H.temperatures(record, piece, heat, X.T_REF, step.state.material.phases)[0]
        rows = [(top(out.cohort(p.cohort_id), p, out.heat_j(i).tolist()), p.area_m2)
                for i, p in enumerate(step.state.material.pieces()) if p.face_id == 's00-merged']
        self.assertNotEqual(rows[0][1], rows[1][1])
        independent = math.fsum(v*a for v, a in rows)/math.fsum(a for _, a in rows)
        mean = H.face_mean(out, step.state, 's00-merged', top, occupied=lambda record: True)
        self.assertLessEqual(abs(mean-independent), 1e-12*independent)
        self.assertGreater(abs(mean-(rows[0][0]+rows[1][0])/2), 1e-6)

    def test_the_maximum_principle_check_fires(self):
        """The check is a guard: the monotone scheme never trips it, so a vertical solve that undershoots by 1 K (below
        every starting and boundary temperature of the steady cold columns) is injected here (patched in this test
        only); the source-free step then refuses by name, before the energy closure."""
        network, nodes, state, moving = small_hot_cold()
        step = X.stepped(state, still(network))
        exact = H._heat.conduct

        def overshooting(*args, **kwargs):
            theta, integral = exact(*args, **kwargs)
            return theta-1., integral
        with mock.patch.object(H._heat, 'conduct', overshooting):
            with self.assertRaises(H.ThermalRefused) as caught:
                M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction('solve', nodes)))
        self.assertEqual(caught.exception.detail, 'maximum principle')

    def test_nodes_are_checked_against_their_faces(self):
        network = F.sector_world()
        state, moving = warm_cold(network)
        step = X.stepped(state, still(network))
        nodes = X.nodes(network)
        antipodes = tuple((face, tuple(-x for x in d)) for face, d in nodes)
        unknown = nodes+(('no-such-face', F.direction(10., 10.)),)
        for bad in (antipodes, unknown):
            with self.assertRaises(H.ThermalRefused) as caught:
                M.advance_moving(moving, state, step, M.MovingAdvance(0, 1, conduction=M.Conduction('solve', bad)))
            self.assertEqual(caught.exception.code, M.INCOMPATIBLE)
        with self.assertRaises(M.TransportRefused) as caught:
            M.Conduction('solve', (('s00-b00', (0., 0., 0.)),))
        self.assertEqual(caught.exception.code, M.MISSING)

    def test_means_check_their_state_and_inputs(self):
        network = F.three_plates()
        cohort_of = {'s00-b01': 'ocean-young', 's00-b02': 'ocean-old'}
        state = X.crust(network, cohort_of=lambda f: cohort_of.get(f, 'continent'))
        records = (X.record('continent'), X.record('ocean-young', top=500., bottom=900.), X.record('ocean-old'))
        moving = M.declare_moving(state, records, enthalpy_reference_k=X.T_REF)
        from test_i05_transport import merged_face, remesh
        step = X.stepped(state, remesh(state, ('s00-b01', 's00-b02'), (merged_face(),)))
        out = M.advance_moving(moving, state, step, M.MovingAdvance(0, 1)).state

        def top(record, piece, heat):
            return H.temperatures(record, piece, heat, X.T_REF, step.state.material.phases)[0]
        with self.assertRaises(M.TransportRefused) as caught:            # the parent's state, the endpoint's sphere
            H.face_mean(moving, step.state, 's00-merged', top, occupied=lambda r: True)
        self.assertEqual(caught.exception.code, M.STALE)
        with self.assertRaises(H.ThermalRefused) as caught:
            H.face_mean(out, step.state, 'no-such-face', top, occupied=lambda r: True)
        self.assertEqual(caught.exception.code, M.MISSING)
        for rows in ([(500., -1.)], [(500., math.nan)], [(500., math.inf)], [(math.nan, 1.)], [(None, 1.)],
                     [(500., True)], [(500., None)]):
            with self.assertRaises(H.ThermalRefused, msg=str(rows)):
                H.occupied_mean(rows)


if __name__ == '__main__':
    unittest.main()
