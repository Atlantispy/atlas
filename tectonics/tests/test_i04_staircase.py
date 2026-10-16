"""Nonzero full D1/D2 intervals on the predeclared C2 equatorial staircase control.

Inputs and criteria were saved in i04_staircase_v1.json before execution. A/B are explicitly rigid multipart plates;
the same half-turn symmetry holds for their geometry, material and forcing, not a projection of the solved motion.
The two transform belts act; ridge/trench resistance is explicitly omitted and is not claimed tested here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
from dataclasses import replace
import json
import math
from pathlib import Path
import unittest

import numpy as np

import i03_fixtures as F
import i03_staircase_fixtures as Q
import i04_fixtures as F4
import i04_strength_fixtures as Z
from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_feedback as B
from atlas_tectonics import integration_ports as P
from atlas_tectonics import integration_strength as G


CASE = json.loads((Path(__file__).resolve().parents[1]/'cases'/'i04_staircase_v1.json').read_text(encoding='utf-8'))
SOURCE = 'test: tectonics/cases/i04_staircase_v1.json (authored C2 multipart staircase)'


def fixture(tilt=None):
    width = CASE['belt_width_m']
    lats = Z.twin_latitudes(width_m=width)
    # A left belt lies south of each west-directed transform, on its carrier A, to the full width from the equator.
    lats = sorted(set(lats+[-math.degrees(width/F.RADIUS_M)]))
    state = Z.crust(Q.paired_network(fraction=CASE['ridge_accretion_fraction'], tilt=tilt, latitudes_deg=lats))
    moving = Z.moving(state)
    declaration = Z.declaration(boundaries=tuple(CASE['belt_boundaries']), width_m=width,
                                ell_m=CASE['d2_length_m'], order=CASE['gauss_order_per_layer'])
    belts = tuple((name, G.Belt(b.width_m, b.length_m, b.healing_law_id, b.width_source, b.length_source,
                               CASE['belt_side'])) for name, b in declaration.belts)
    declaration = G.Declaration(belts, declaration.materials, declaration.creep_laws, declaration.order, SOURCE)
    forcing = D.Forcing(tuple((p, CASE['basal_drag_pa_s_m']) for p in ('A', 'B')), SOURCE,
                        authored_torque_n_m=(('B', tuple(CASE['authored_torque_n_m']*np.asarray(F.axis(tilt)))),),
                        omitted=tuple(CASE['omitted_forces']), slab_omitted=Q.PAIRED_TRENCHES,
                        belts=tuple(CASE['belt_boundaries']), frame_id=F.FRAME)
    supplies = tuple(supply for name in Q.PAIRED_RIDGES for supply in Z.supplies(name))
    inputs = B.Inputs(forcing, declaration, F4.datum(),
                      template=(('supplies', supplies), ('sinks', tuple(F.sink(name) for name in Q.PAIRED_TRENCHES))),
                      births=Z.births())
    return state, moving, inputs


class OneSidedCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state, moving, inputs = fixture()
        interval = Z.interval(state, CASE['interval_myr'])
        balance, _, _, _ = B.solve_at(state, moving, inputs, interval=interval,
                                      parent_state_id=state.state_id, evaluation='start')
        motion = B._motion_port(state, inputs, interval, balance.omega_rad_s, balance.balance_id, None)
        step, _, end_moving, _, _ = B._advance(state, moving, motion, inputs, {}, interval)
        cls.state = step.state
        cls.support = P.trace_support(step.state.network)
        _, cls.term, _, _ = B.solve_at(step.state, end_moving, inputs, interval=interval,
                                       parent_state_id=state.state_id, evaluation='end')

    def test_newborn_face_on_wrong_geometric_side_is_not_a_missed_belt_face(self):
        network = self.state.network
        face = next(f for f in network.faces if f.face_id == 'ridge-north-0|left|1|0000')
        index = {v: i for i, v in enumerate(network.vertex_ids)}
        centre = np.sum(network.vertex_direction[[index[v] for v in face.vertex_ids]], axis=0)
        centre /= np.linalg.norm(centre)
        candidates = []
        for line in self.term.lines:
            if line.boundary_id == 'transform-step-0':
                a_id, b_id = G.edge_vertices(network, self.support, line.edge)
                a, b = network.vertex_direction[[index[a_id], index[b_id]]]
                pole = np.cross(a, b)
                pole /= np.linalg.norm(pole)
                candidates.append((G._point_arc_distance(centre, a, b, pole), line, pole))
        distance, line, pole = min(candidates, key=lambda item: item[0])
        self.assertEqual(line.belt.side, 'left')
        self.assertEqual(face.plate_id, 'A')
        self.assertLess(float(centre @ pole), -G.S.ATTACHMENT_BAND_RAD)
        self.assertLess(distance, line.belt.width_m/self.term.radius)
        self.assertNotIn(face.face_id, self.term.coverage)

    def test_omitted_face_on_selected_side_still_refuses(self):
        original = self.term.lines
        face_id = original[0].cells[0].cell.face_id
        self.term.lines = tuple(replace(line, cells=tuple(c for c in line.cells if c.cell.face_id != face_id))
                                for line in original)
        try:
            with self.assertRaises(G.StrengthRefused) as caught:
                self.term._coverage(self.state.network, self.support)
            self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'missed'))
        finally:
            self.term.lines = original
            self.term._coverage(self.state.network, self.support)


class StaircaseFeedback(unittest.TestCase):
    def test_nonzero_coupled_intervals_preserve_the_ridge_transform_staircase(self):
        self.check_intervals()

    def test_tilted_coupled_intervals_preserve_the_staircase_and_positive_history(self):
        self.check_intervals(F.rotation(CASE['orientations']['tilted']))

    def check_intervals(self, tilt=None):
        state, moving, inputs = fixture(tilt)
        axis = np.asarray(F.axis(tilt))
        self.receipts = []
        previous = None
        for _ in range(CASE['intervals']):
            result = B.coupled_interval(state, moving, inputs, interval=Z.interval(state, CASE['interval_myr']),
                                        parent=previous)
            self.assertLessEqual(result.report['residual'], B.OUTER_RELATIVE)
            self.assertTrue(result.step.state.material.closure()['identity_exact'])
            self.assertGreater(result.balance.belt['dissipation_w'], 0.)
            self.assertGreater(float(np.max(result.increment_port.kappa_increment)), 0.)
            self.assertEqual(set(result.balance.omitted_interfaces), set(CASE['omitted_interface_boundaries']))
            omega = np.asarray(result.motion_port.omega_rad_s)
            axial = omega @ axis
            self.assertGreater(axial[1]-axial[0], 0.)
            relative = np.linalg.norm(omega-axial[:, None]*axis)/np.linalg.norm(axial)
            self.assertLess(float(relative), CASE['criteria']['coaxial_relative'])
            births = result.step.summary()['births']
            self.assertGreater(sum(float(Fraction(row['area_m2'])) for row in births), 0.)
            self.assertTrue(all(row['boundary_id'] in Q.PAIRED_RIDGES for row in births))
            network = result.step.state.network
            index = {name: i for i, name in enumerate(network.vertex_ids)}
            order = {plate: i for i, plate in enumerate(network.plate_ids)}
            frames, poles = dict(network._layout.frames), dict(network._layout.poles)
            maximum_slip = 0.
            maximum_offset = 0.
            for boundary in network.boundaries:
                if boundary.boundary_id in Q.PAIRED_TRANSFORMS:
                    points = network.vertex_direction[[index[v] for v in boundary.vertex_ids]]
                    self.assertLess(float(np.max(np.abs(points @ axis))), CASE['criteria']['offset_absolute_rad'])
                    offset = float(F.angle(points[0], points[-1]))
                    maximum_offset = max(maximum_offset, abs(offset-math.radians(20.)))
                    self.assertLess(maximum_offset, CASE['criteria']['offset_absolute_rad'])
                    relative_frame = frames['B'].then(frames['A'].inverse())
                    local_trace = network._local[order['A']][[index[v] for v in boundary.vertex_ids]]
                    slip = float(np.max(np.abs(relative_frame.apply(local_trace)
                                               @ np.asarray(poles[(boundary.boundary_id, 'trace')]))))
                    maximum_slip = max(maximum_slip, slip)
                    self.assertLessEqual(slip, G.S.ATTACHMENT_BAND_RAD)
                    for end in (boundary.vertex_ids[0], boundary.vertex_ids[-1]):
                        junction = next(j for j in network.junctions if j.vertex_id == end)
                        names = {name for name, _ in junction.boundary_ends}
                        self.assertEqual(len(names), 2)
                        self.assertTrue(names & set(Q.PAIRED_RIDGES))
            self.receipts.append(dict(step=network.step, iterations=result.report['iterations'],
                                      residual=result.report['residual'], omega_axial_rad_s=axial.tolist(),
                                      coaxial_relative=float(relative), c6_cumulative_rad=maximum_slip,
                                      offset_error_rad=maximum_offset,
                                      birth_area_m2=sum(float(Fraction(row['area_m2'])) for row in births),
                                      belt_work_w=result.balance.belt['dissipation_w'],
                                      p6_max=float(np.max(result.increment_port.kappa_increment)),
                                      p7_closure_relative=result.report['p7_closure_relative']))
            state, moving, previous = result.step.state, result.moving, result


if __name__ == '__main__':
    unittest.main()
