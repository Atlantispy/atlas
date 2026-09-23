"""Independent metric and whole-support checks for the Stage-7 geometry bridge."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import math
import threading
import unittest

from atlas_tectonics import (BoundaryRegion, GeologicalCase, RegionalGrid1D,
    SphericalChart, SphericalFrame, SphericalPatch, build_boundary_network,
    build_spherical_atlas, GeologyError)
from atlas_tectonics.regional_workflow_geometry import RegionalColumnSupport, build_workflow_cells
from atlas_tectonics.regional_forcing import PreparedRegionalForcing, MotionReductionError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from test_w01_geological_description import ingredients, column, layer
from test_w01_initial_sampling import initial
from test_w01_regional_forcing import (SOURCE, atlas, box, definition, faces,
    motion, network, planar, reduction, spherical)


def state(topology, **changes):
    args = ingredients(topology)
    args.update(epoch_id='epoch', columns=(column(layers=(layer(thickness=4.),)),))
    args.update(changes)
    return initial(GeologicalCase(**args))


def forcing(topology=None, *, width=2., cells=4, section=None, motions=None):
    topology = network() if topology is None else topology
    section = planar() if section is None else section
    r = replace(reduction(), reference_width_m=width)
    with PreparedRegionalForcing(definition(topology, motions), section, r) as plan:
        return faces(plan, RegionalGrid1D(cells, section.length_m))


class WorkflowGeometry(unittest.TestCase):
    def test_planar_exact_strip_area_depth_and_refinement(self):
        net = network(); s = state(net)
        support = RegionalColumnSupport('planar-strip', 0., 4., SOURCE)
        for count in (1, 4, 8):
            result = build_workflow_cells(s, forcing(net, cells=count), support)
            self.assertEqual(len(result), count)
            self.assertEqual(math.fsum(c.volume_m3 for c in result), 80.)
            for c in result:
                self.assertEqual(c.footprint.area_m2, 20./count)
                self.assertEqual(c.footprint.bounds[1::2], (4., 6.))

    def test_planar_strip_must_be_wholly_inside_domain(self):
        net = network(); s = state(net)
        f = forcing(net, width=12.)  # The section itself remains wholly covered.
        with self.assertRaisesRegex(GeologyError, 'outside|clipping'):
            build_workflow_cells(s, f, RegionalColumnSupport('planar-strip', 0., 4., SOURCE))

    def test_off_centre_owner_with_different_motion_is_refused(self):
        net = build_boundary_network(box(), (
            BoundaryRegion('lower', 'A', box(y1=6.)),
            BoundaryRegion('upper', 'B', box(y0=6.))))
        s = state(net)
        mm = (motion('A'), motion('B', translation=(2., 0., 0.)))
        f = forcing(net, width=4., motions=mm)
        with self.assertRaisesRegex(MotionReductionError, 'whole column footprint'):
            build_workflow_cells(s, f, RegionalColumnSupport('planar-strip', 0., 4., SOURCE))
        # A separate supported footprint that misses B is still admitted.
        narrow = forcing(net, width=1., motions=mm)
        self.assertEqual(len(build_workflow_cells(s, narrow,
            RegionalColumnSupport('planar-strip', 0., 4., SOURCE))), 4)

    def test_north_and_south_shell_volume_analytic_and_refined(self):
        net = atlas(SphericalFrame(10., 'world')); s = state(net)
        d, section = spherical(net, length=5*math.pi)
        support = RegionalColumnSupport('north-hemisphere', 0., 2., SOURCE)
        r = replace(reduction(True), reference_width_m=10.)
        expected = 244*math.pi/3  # ((10^3 - 8^3)/3) * (pi/2).
        for count in (1, 2, 4):
            with PreparedRegionalForcing(d, section, r) as plan:
                f = faces(plan, RegionalGrid1D(count, section.length_m))
            for kind in ('north-hemisphere', 'south-hemisphere'):
                cells = build_workflow_cells(s, f, replace(support, kind=kind))
                self.assertEqual(len(cells), count)
                self.assertAlmostEqual(math.fsum(c.volume_m3 for c in cells), expected, places=11)
                for cell in cells:
                    self.assertAlmostEqual(cell.footprint.area_m2, 50*math.pi/count, places=11)
                    self.assertAlmostEqual(cell.volume_m3/(f.grid.spacing_m*10), 122/75, places=13)

    def test_spherical_interior_owner_away_from_equator_is_refused(self):
        sphere = SphericalFrame(10., 'world')
        vertices = {'px': (1.,0.,0.), 'nx': (-1.,0.,0.), 'py': (0.,1.,0.),
                    'ny': (0.,-1.,0.), 'pz': (0.,0.,1.), 'nz': (0.,0.,-1.),
                    'pxz': (1.,0.,1.), 'nxz': (-1.,0.,1.),
                    'pyz': (0.,1.,1.), 'nyz': (0.,-1.,1.)}
        patches = []
        # Split every northern octant at shared meridian midpoints. The B cap
        # never touches the equatorial section, but has positive wedge volume.
        for sx in (-1, 1):
            for sy in (-1, 1):
                x = ('p' if sx > 0 else 'n')+'x'
                y = ('p' if sy > 0 else 'n')+'y'
                for label, ids, plate, sign in (
                    ('lower', (x,y,y+'z',x+'z'), 'A', sx*sy),
                    ('cap', (x+'z',y+'z','pz'), 'B', sx*sy),
                    ('south', (x,y,'nz'), 'A', -sx*sy)):
                    if sign < 0:
                        ids = tuple(reversed(ids))
                    centre = (sx,sy,-1 if label == 'south' else 1)
                    name = label+str(sx)+str(sy)
                    plate = 'B' if label == 'cap' and sx == sy == 1 else 'A'
                    patches.append(SphericalPatch(name, name, plate, ids, SphericalChart(sphere,centre)))
        net = build_spherical_atlas(sphere, vertices, tuple(patches))
        s = state(net)
        d, section = spherical(net, length=5*math.pi)
        d = replace(d, motions=(motion('A', frame='world', mode='spherical-euler',
            translation=(0.,0.,0.), omega=(0.,0.,1.)), motion('B', frame='world',
            mode='spherical-euler', translation=(0.,0.,0.), omega=(0.,0.,2.))))
        with PreparedRegionalForcing(d, section, reduction(True)) as plan:
            f = faces(plan, RegionalGrid1D(1, section.length_m))
        with self.assertRaisesRegex(MotionReductionError, 'whole column footprint'):
            build_workflow_cells(s, f, RegionalColumnSupport('north-hemisphere', 0., 2., SOURCE))

    def test_topology_epoch_time_and_reduction_mismatch(self):
        net = network(); f = forcing(net)
        support = RegionalColumnSupport('planar-strip', 0., 4., SOURCE)
        for s in (state(network(split=True)), state(net, epoch_id='different'), state(net, time_s=1.)):
            with self.assertRaisesRegex(MotionReductionError, 'mismatch'):
                build_workflow_cells(s, f, support)
        with self.assertRaisesRegex(MotionReductionError, 'reductions disagree'):
            build_workflow_cells(state(net), f, replace(support, kind='north-hemisphere'))

    def test_support_contract_cancellation_and_memory_release(self):
        for args in (('latitude-strip', 0., 1., SOURCE), ('planar-strip', 2., 1., SOURCE),
                     ('planar-strip', 0., 1., None)):
            with self.assertRaises(MotionReductionError):
                RegionalColumnSupport(*args)
        support = RegionalColumnSupport('planar-strip', 0., 4., SOURCE)
        with self.assertRaises(FrozenInstanceError):
            support.kind = 'north-hemisphere'
        net = network(); s = state(net); f = forcing(net)
        cancel = threading.Event(); cancel.set()
        budget = WorkBudget(1024)
        with self.assertRaises(CancelledError):
            build_workflow_cells(s, f, support, budget=budget, cancel=cancel)
        with self.assertRaises(MemoryLimitError):
            build_workflow_cells(s, f, support, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        budget = WorkBudget(1024**2)
        self.assertEqual(len(build_workflow_cells(s, f, support, budget=budget)), 4)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
