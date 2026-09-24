"""Analytic spherical controls; native compact fixtures, no physical evolution."""
from dataclasses import FrozenInstanceError, replace
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from concurrent.futures import CancelledError

import numpy as np

TECTONICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TECTONICS/'src'), str(TECTONICS/'tools')]
import new_world_arcs as arcs
from new_world_contract import ContractError
from new_world_structure import WorldStructure
from atlas_tectonics import (SphericalFrame, SphericalChart, SphericalGeometry,
    build_spherical_atlas, FeatureGeometry, GeologicalProvince, SurfaceSelector,
    FeaturePrecedence)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from test_w01_spherical_atlas import octants
import precursor_fixtures as native

SPHERE = SphericalFrame(6371000., 'arc-control')


def point(longitude, latitude=0.):
    lon, lat = map(math.radians, (longitude, latitude))
    return np.array([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)])


def world(ring, *, rotation=None, subdivide=False, sphere=SPHERE, second=None):
    rotation = np.eye(3) if rotation is None else rotation
    vertices, patches = octants(sphere=sphere)
    vertices = {name: rotation@value for name, value in vertices.items()}
    patches = tuple(replace(p, plate_id=p.patch_id, region_id=p.patch_id,
        chart=SphericalChart(sphere, tuple(rotation@np.asarray(p.chart.centre)))) for p in patches)
    if subdivide:
        vertices['middle'] = rotation@point(45.)
        refined = []
        for p in patches:
            ids = []
            for first, last in zip(p.vertex_ids, p.vertex_ids[1:]+p.vertex_ids[:1]):
                ids.append(first)
                if {first, last} == {'px', 'py'}:
                    ids.append('middle')
            refined.append(replace(p, vertex_ids=tuple(ids)))
        patches = tuple(refined)
    atlas = build_spherical_atlas(sphere, vertices, patches)
    def polygon(values):
        points = np.asarray([rotation@point(*value) for value in values])
        # An equatorial chart retains exactly zero z for the exact-touch and
        # coincident-edge controls; a tilted chart can introduce a real ULP gap.
        centre = point(0.) if (0.,0.) in values else point(45.)
        return SphericalGeometry.polygon(points, chart=SphericalChart(sphere, tuple(rotation@centre)))
    geometries = [FeatureGeometry('crust', polygon(ring), 'fixture')]
    provinces = [GeologicalProvince('background', 'continent', SurfaceSelector('domain'), 'fixture'),
                 GeologicalProvince('feature', 'ocean', SurfaceSelector('geometry', ('crust',)), 'fixture')]
    columns = [native.column(), native.column('ocean', crust_type='oceanic')]
    order = ('feature', 'background')
    if second:
        geometries.append(FeatureGeometry('priority', polygon(second), 'fixture'))
        provinces.append(GeologicalProvince('priority', 'priority', SurfaceSelector('geometry', ('priority',)), 'fixture'))
        columns.append(native.column('priority'))
        order = ('priority', 'feature', 'background')
    case = native.case(sphere, columns=tuple(columns), geometries=tuple(geometries),
                       provinces=tuple(provinces), precedence=FeaturePrecedence(order))
    return atlas, WorldStructure(native.state(case), {})


def edge_rows(atlas, rows, pair=('px', 'py')):
    ident = next(i for i, (a, b) in enumerate(atlas.edge_vertices)
                 if {atlas.vertex_ids[a], atlas.vertex_ids[b]} == set(pair))
    selected = [row for row in rows if row.edge_index == ident]
    a = atlas.vertex_ids[atlas.edge_vertices[ident, 0]]
    if a != pair[0]:
        selected = [replace(row, start_fraction=1-row.end_fraction,
                            end_fraction=1-row.start_fraction) for row in selected[::-1]]
    return selected


RECTANGLE = ((30., -10.), (60., -10.), (60., 10.), (30., 10.))


class ArcCrustTests(unittest.TestCase):
    def test_crossings_complete_partition_and_precedence(self):
        atlas, structure = world(RECTANGLE)
        rows = arcs.crust_intervals(atlas, structure)
        selected = edge_rows(atlas, rows)
        spans = [r for r in selected if r.start_fraction < r.end_fraction]
        self.assertEqual([r.column_ids for r in spans], [('continent',), ('ocean',), ('continent',)])
        np.testing.assert_allclose([(r.start_fraction, r.end_fraction) for r in spans],
                                    [(0, 1/3), (1/3, 2/3), (2/3, 1)], atol=2e-14, rtol=0)
        self.assertEqual([r.column_ids for r in selected if r.start_fraction == r.end_fraction],
                         [('ocean', 'continent')]*2)
        for index in atlas.interplate_edges:
            parts = [r for r in rows if r.edge_index == index and r.start_fraction < r.end_fraction]
            self.assertEqual(parts[0].start_fraction, 0.)
            self.assertEqual(parts[-1].end_fraction, 1.)
            self.assertEqual([r.end_fraction for r in parts[:-1]], [r.start_fraction for r in parts[1:]])
        atlas, structure = world(((20.,-10.),(70.,-10.),(70.,10.),(20.,10.)), second=RECTANGLE)
        contacts = [r for r in edge_rows(atlas, arcs.crust_intervals(atlas, structure))
                    if r.start_fraction == r.end_fraction and abs(r.start_fraction-1/3)<1e-13]
        self.assertEqual(contacts[0].column_ids, ('priority', 'ocean'))

    def test_pole_and_antimeridian_are_rotation_invariant(self):
        q = math.sqrt(.5)
        polar = np.array([[q,-q,0.],[0.,0.,-1.],[q,q,0.]])
        angle = math.radians(135.)
        seam = np.array([[math.cos(angle),-math.sin(angle),0.],
                         [math.sin(angle),math.cos(angle),0.],[0.,0.,1.]])
        for rotation in (polar, seam):
            with self.subTest(rotation=rotation.tolist()):
                atlas, structure = world(RECTANGLE, rotation=rotation)
                spans = [r for r in edge_rows(atlas, arcs.crust_intervals(atlas, structure))
                         if r.start_fraction < r.end_fraction]
                self.assertEqual([r.column_ids for r in spans], [('continent',), ('ocean',), ('continent',)])
                np.testing.assert_allclose([r.end_fraction for r in spans], [1/3,2/3,1], atol=2e-14, rtol=0)

    def test_tangent_vertex_and_endpoint_remain_ambiguous_contacts(self):
        for ring, position in ((((30.,20.),(45.,0.),(60.,20.)), .5),
                               (((-15.,20.),(0.,0.),(15.,20.)), 0.)):
            atlas, structure = world(ring)
            rows = edge_rows(atlas, arcs.crust_intervals(atlas, structure))
            self.assertTrue(all(r.column_ids == ('continent',) for r in rows if r.start_fraction < r.end_fraction))
            contacts = [r for r in rows if r.start_fraction == r.end_fraction]
            self.assertEqual(len(contacts), 1)
            self.assertAlmostEqual(contacts[0].start_fraction, position, places=13)
            self.assertEqual(contacts[0].column_ids, ('ocean', 'continent'))

    def test_coincident_boundary_has_positive_length_ambiguity(self):
        atlas, structure = world(((30.,0.),(60.,0.),(45.,20.)))
        spans = [r for r in edge_rows(atlas, arcs.crust_intervals(atlas, structure))
                 if r.start_fraction < r.end_fraction]
        self.assertEqual([r.column_ids for r in spans], [('continent',), ('ocean','continent'), ('continent',)])
        np.testing.assert_allclose([(r.start_fraction,r.end_fraction) for r in spans],
                                    [(0,1/3),(1/3,2/3),(2/3,1)], atol=2e-14, rtol=0)

    def test_native_edge_subdivision_preserves_angular_column_measure(self):
        totals = []
        for subdivide in (False, True):
            atlas, structure = world(RECTANGLE, subdivide=subdivide)
            rows = arcs.crust_intervals(atlas, structure)
            selected = edge_rows(atlas, rows) if not subdivide else (
                edge_rows(atlas, rows, ('px','middle'))+edge_rows(atlas, rows, ('middle','py')))
            scale = math.pi/4 if subdivide else math.pi/2
            totals.append({key: math.fsum((r.end_fraction-r.start_fraction)*scale
                          for r in selected if r.column_ids == (key,)) for key in ('continent','ocean')})
        for key in totals[0]:
            self.assertAlmostEqual(totals[0][key], totals[1][key], places=13)
        self.assertAlmostEqual(totals[0]['ocean'], math.pi/6, places=13)

    def test_source_frame_degeneracy_budget_cancellation_and_immutability_guards(self):
        atlas, structure = world(RECTANGLE)
        budget = WorkBudget(1 << 20)
        rows = arcs.crust_intervals(atlas, structure, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertGreater(budget.peak_reserved_bytes, 0)
        with self.assertRaises(FrozenInstanceError): rows[0].edge_index = 9
        with self.assertRaises(MemoryLimitError): arcs.crust_intervals(atlas, structure, budget=WorkBudget(1))
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError): arcs.crust_intervals(atlas, structure, cancel=event)
        other, _ = world(RECTANGLE, sphere=SphericalFrame(SPHERE.radius_m,'foreign'))
        with self.assertRaisesRegex(ContractError, 'frame'): arcs.crust_intervals(other, structure)
        for b in ((1.,0.,0.), (-1.,1e-15,0.), (-1.,1e-10,0.)):
            with self.assertRaisesRegex(ContractError, 'Degenerate|antipodal'): arcs._arc_frame((1.,0.,0.), b)
        # An extremely small plane angle is not a coincident arc. The adaptive
        # exact predicate still finds its isolated equatorial crossing.
        c, d = point(30.), point(60.)
        c[2], d[2] = 1e-15, -1e-15
        length, normal, tangent = arcs._arc_frame(c,d)
        angle, intervals, _ = arcs._edge_partition(point(0.),point(90.),
            np.asarray([c]),np.asarray([d]),np.asarray([normal]),np.asarray([tangent]),
            np.asarray([length]),['near-plane'])
        contacts = [lo/angle for lo,hi,_ in intervals if lo == hi]
        np.testing.assert_allclose(contacts,[.5],atol=2e-14,rtol=0)
        self.assertTrue(all(not keys for lo,hi,keys in intervals if lo < hi))
        with patch.object(arcs, '_LOADED_HASH', '0'*64):
            with self.assertRaisesRegex(ContractError, 'changed'): arcs.crust_intervals(atlas, structure)


if __name__ == '__main__': unittest.main()
