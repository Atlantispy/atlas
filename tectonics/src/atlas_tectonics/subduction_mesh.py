"""Bounded interface-aligned P2 mesh in paper coordinates: km, x right, y down.

Straight triangles carry vertices then edge midpoints 01, 12, 20. Areas are km2,
barycentric gradients km-1, and P2 Laplacians km-2. No implicit SI/sign conversion.
Quadrature weights sum to one; physical integration multiplies by triangle area.

Default grading interface-r3 uses s=sqrt(h/6) and the target
edge spacing in km is min(45*s, h+s*(.25*d_slab+.1*max(s_slab-225,0)),
                              h+s*(.25*d_lid+.1*max(x-225,0))). Here d is physical normal distance,
s_slab=(x+y)/2, and d_lid is distance to the ray (x>=50,y=50). Thus the normal
growth and remote cap now also vanish as h tends to zero. Normal boundary layers
refine with h; smooth remote regions refine with sqrt(h). Unlike r2, this is a
globally refining family, while avoiding unnecessarily uniform boundary-layer
resolution. The deterministic .9*local-h interior exclusion and exact shared
boundary partition remain. Experimental corner-r4/r5 add geometric targets at the singular
wedge apex (50,50): h/4+s*(.05*r+.5*max(r-25,0)+.25*d_outside_wedge), and
h/6000+s*(.35*r+.25*d_outside_wedge). The 25 km transition is half the 50 km
lid thickness, not a fitted temperature contour. The minimum apex targets for
h=6,3,1.5 km are 1,.5,.25 m; h is now the interface/base scale, not the minimum.
corner-r5 uses h/60 instead of h/6000 (100,50,25 m) to avoid the extreme
pressure conditioning observed with corner-r4. Both remain explicit candidates.
These targets were fixed using geometry/conditioning before a physics comparison.
They do not reproduce the reference PGC's 1 m notch or claim physical acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from itertools import permutations
import math
import threading

import numpy as np
from scipy.spatial import Delaunay, QhullError

from ._validation import TectonicsError, scalar, input_shape, read_array
from .constitutive import _cancel
from .resources import WorkBudget, select_budget


MAX_ELEMENTS = 20000
GRADINGS = {'interface-r3': 'w08-subduction-interface-sqrt-growth-r3',
    'corner-r4': 'w08-subduction-corner-sqrt-growth-r4',
    'corner-r5': 'w08-subduction-corner-sqrt-growth-r5'}
_MAX_VERTICES = 12000
_MAX_CANDIDATES = 4*_MAX_VERTICES  # temporary cloud, not admitted retained vertices
_CAP = 128*1024**2
_EDGES = ((0, 1), (1, 2), (2, 0))
_POLYGONS = (((0., 0.), (600., 600.), (0., 600.)),
    ((0., 0.), (660., 0.), (660., 50.), (50., 50.)),
    ((50., 50.), (660., 50.), (660., 600.), (600., 600.)))
_SEGMENTS = (((0., 0.), (50., 50.)), ((50., 50.), (600., 600.)),
    ((0., 0.), (0., 600.)), ((0., 600.), (600., 600.)),
    ((0., 0.), (660., 0.)), ((660., 0.), (660., 50.)),
    ((50., 50.), (660., 50.)), ((660., 50.), (660., 600.)),
    ((600., 600.), (660., 600.)))
_REGION_SEGMENTS = ((0, 1, 2, 3), (0, 4, 5, 6), (1, 6, 7, 8))


def _frozen(a, dtype=None):
    a = np.asarray(a, dtype=dtype)
    return np.frombuffer(a.tobytes(), dtype=a.dtype).reshape(a.shape)


def quadrature(degree=5):
    """Positive Strang 7/9 rules: degree 5/6, 7/12 nodes, area-normalised weights."""
    if type(degree) is not int or degree not in (5, 6):
        raise TectonicsError('triangle quadrature supports degree 5 or 6')
    if degree == 5:
        groups = [((1/3, 1/3, 1/3), .225),
            ((.7974269853530873, .10128650732345633, .10128650732345633), .12593918054482717),
            ((.05971587178976981, .4701420641051151, .4701420641051151), .13239415278850616)]
    else:
        groups = [((.873821971016996, .063089014491502, .063089014491502), .050844906370207),
            ((.501426509658180, .249286745170910, .249286745170910), .116786275726379),
            ((.636502499121399, .310352451033785, .053145049844816), .082851075618374)]
    bary, weights = [], []
    for point, weight in groups:
        nodes = sorted(set(permutations(point)))
        bary.extend(nodes); weights.extend([weight]*len(nodes))
    return _frozen(bary), _frozen(weights)


def basis(bary, grad_lambda=None, *, budget=None, cancel=None):
    """Return N[Q,6], or (N, dN[E,Q,6,2], lapN[E,6]); caller owns result storage."""
    shape = input_shape(bary)
    if len(shape) != 2 or shape[1] != 3 or not 1 <= shape[0] <= 4096:
        raise TectonicsError('bounded Q by 3 barycentric coordinates required')
    gs = None if grad_lambda is None else input_shape(grad_lambda)
    if gs is not None and (len(gs) != 3 or gs[1:] != (3, 2) or not 1 <= gs[0] <= MAX_ELEMENTS):
        raise TectonicsError('bounded E by 3 by 2 barycentric gradients required')
    count = shape[0]*(1 if gs is None else gs[0])
    owner = WorkBudget(_CAP, parent=select_budget(budget))
    with owner.reserve(384*count+65536, category='subduction-basis'):
        _cancel(cancel); b = read_array(bary, 'barycentric coordinates')
        if np.max(np.abs(b.sum(axis=1)-1.)) > 2e-13 or np.min(b) < -2e-11 or np.max(b) > 1.+2e-11:
            raise TectonicsError('point lies outside its triangle')
        n = np.column_stack([b[:, i]*(2*b[:, i]-1) for i in range(3)]+
                            [4*b[:, i]*b[:, j] for i, j in _EDGES])
        if gs is None:
            _cancel(cancel); return n
        g = read_array(grad_lambda, 'barycentric gradients')
        scale = max(float(np.max(np.abs(g))), np.finfo(float).tiny)
        if np.max(np.abs(g.sum(axis=1))) > 2e-13*scale:
            raise TectonicsError('barycentric gradients do not sum to zero')
        dn = np.empty((gs[0], shape[0], 6, 2)); lap = np.empty((gs[0], 6))
        for i in range(3):
            dn[:, :, i] = (4*b[None, :, i, None]-1)*g[:, None, i]
            lap[:, i] = 4*np.sum(g[:, i]*g[:, i], axis=1)
        for k, (i, j) in enumerate(_EDGES, 3):
            dn[:, :, k] = 4*(b[None, :, i, None]*g[:, None, j]+b[None, :, j, None]*g[:, None, i])
            lap[:, k] = 8*np.sum(g[:, i]*g[:, j], axis=1)
        _cancel(cancel); return n, dn, lap


def _target(x, y, spacing, grading='interface-r3'):
    scale = math.sqrt(spacing/6.)
    slab = spacing+scale*(.1*max(0., (x+y)/2-225.)+.25*abs(x-y)/math.sqrt(2.))
    lid = spacing+scale*(.1*max(0., x-225.)+.25*math.hypot(max(0., 50.-x), y-50.))
    base = min(45.*scale, slab, lid)
    if grading == 'interface-r3': return base
    # Both prescribed traces meet at a point with a singular strain field.
    # Resolve that geometric singularity independently of reference temperatures;
    # retain r3's global refinement away from it. No finite coupling ramp is added.
    radius = math.hypot(x-50., y-50.)
    outside = math.hypot(max(0.,y-x)/math.sqrt(2.),max(0.,50.-y))
    corner = .25*spacing+scale*(.05*radius+.5*max(0.,radius-25.)+.25*outside)
    tip = spacing/(6000. if grading == 'corner-r4' else 60.)+scale*(.35*radius+.25*outside)
    return min(base, corner, tip)


def _segment_points(a, b, spacing, cancel, grading):
    result = [a]; pending = [(a, b)]
    while pending:
        _cancel(cancel); left, right = pending.pop()
        middle = tuple((x+y)/2 for x, y in zip(left, right))
        target = min(_target(*p, spacing, grading) for p in (left, middle, right))
        if math.dist(left, right) > target:
            if len(result)+len(pending) > _MAX_VERTICES:
                raise TectonicsError('subduction boundary exceeds vertex admission')
            pending.extend(((middle, right), (left, middle)))
        else:
            result.append(right)
    return result


def _interior_cloud(spacing, cancel, grading):
    result = [[], [], []]; pending = [(0., 660., 0., 600.)]; visited = 0
    scale = math.sqrt(spacing/6.)
    polygons = [np.asarray(p) for p in _POLYGONS]
    while pending:
        _cancel(cancel); x0, x1, y0, y1 = pending.pop(); visited += 1
        if visited > 8*_MAX_VERTICES:
            raise TectonicsError('subduction refinement exceeds bounded point-cloud work')
        x, y = (x0+x1)/2, (y0+y1)/2
        diagonal = max(0., x0-y1, y0-x1)/math.sqrt(2.)
        horizontal = math.hypot(max(0., 50.-x1), max(0., y0-50., 50.-y1))
        target = min(45.*scale, spacing+scale*(.1*max(0., (x0+y0)/2-225.)+.25*diagonal),
                     spacing+scale*(.1*max(0., x0-225.)+.25*horizontal))
        if grading != 'interface-r3':
            corner_distance = math.hypot(max(0.,x0-50.,50.-x1), max(0.,y0-50.,50.-y1))
            outside_distance = math.hypot(max(0.,y0-x1)/math.sqrt(2.),max(0.,50.-y1))
            target = min(target,
                .25*spacing+scale*(.05*corner_distance+.5*max(0.,corner_distance-25.)+.25*outside_distance),
                spacing/(6000. if grading == 'corner-r4' else 60.)+scale*(.35*corner_distance+.25*outside_distance))
        if max(x1-x0, y1-y0) > target:
            pending.extend(((x0, x, y0, y), (x, x1, y0, y), (x0, x, y, y1), (x, x1, y, y1)))
            continue
        region = 0 if x < y else (1 if y < 50. else 2)
        p = polygons[region]; edges = np.roll(p, -1, axis=0)-p
        cross = edges[:, 0]*(y-p[:, 1])-edges[:, 1]*(x-p[:, 0])
        if np.all(cross/np.linalg.norm(edges, axis=1) > .06*_target(x, y, spacing, grading)):
            result[region].append((x, y))
            if sum(map(len, result)) > _MAX_CANDIDATES:
                raise TectonicsError('subduction interior exceeds bounded candidate work')
    return [_separated(points, spacing, cancel, grading) for points in result]


def _separated(points, spacing, cancel, grading):
    # Quadtree boxes crossing a fine interface over-refine neighbouring interiors.
    # Keep the finest candidates first, with deterministic graded separation.
    ordered = sorted((_target(x, y, spacing, grading), x, y) for x, y in points)
    buckets, result = {}, []
    for target, x, y in ordered:
        _cancel(cancel); level = max(0, int(math.log2(target/spacing))); reject = False
        for k in range(level+1):
            size = spacing*2**k; ix, iy = math.floor(x/size), math.floor(y/size)
            for i in range(ix-2, ix+3):
                for j in range(iy-2, iy+3):
                    for px, py, prior in buckets.get((k, i, j), ()):
                        if math.hypot(x-px, y-py) < .9*min(target, prior):
                            reject = True; break
                    if reject: break
                if reject: break
            if reject: break
        if not reject:
            size = spacing*2**level; key = (level, math.floor(x/size), math.floor(y/size))
            buckets.setdefault(key, []).append((x, y, target)); result.append((x, y))
    return result


def _triangle_geometry(points, cells):
    p = points[cells[:, :3]]
    d1, d2 = p[:, 1]-p[:, 0], p[:, 2]-p[:, 0]
    determinant = d1[:, 0]*d2[:, 1]-d1[:, 1]*d2[:, 0]
    if not np.isfinite(determinant).all() or np.any(determinant <= 0.):
        raise TectonicsError('subduction triangle has non-positive signed area')
    gradients = np.empty((len(cells), 3, 2))
    for i, j, k in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        gradients[:, i, 0] = (p[:, j, 1]-p[:, k, 1])/determinant
        gradients[:, i, 1] = (p[:, k, 0]-p[:, j, 0])/determinant
    return determinant/2, gradients


def _edge_counts(cells):
    counts = {}
    for cell in cells:
        for i, j in _EDGES:
            key = tuple(sorted((int(cell[i]), int(cell[j]))))
            counts[key] = counts.get(key, 0)+1
    if any(n not in (1, 2) for n in counts.values()):
        raise TectonicsError('non-manifold subduction mesh edge')
    return counts


class P2Mesh:
    """Leased immutable geometry. Keep this owner open while using borrowed arrays."""
    __slots__ = ('_closed', '_owner', '_budget', '_vertex_count', '_spacing', '_grading', '_lease', '_arrays', '_locators')
    coordinate_system = 'paper x-right y-down; km'
    def __init__(self, arrays, vertex_count, locators, spacing, budget, grading='interface-r3'):
        import sys
        self._closed = False; self._owner = threading.get_ident(); self._budget = budget
        self._vertex_count = vertex_count; self._spacing = spacing; self._grading = grading
        # SciPy's non-incremental Qhull owner is closed after construction.
        # find_simplex requests only the lazy barycentric transform (not vertex
        # adjacency). Prepare it under the caller's build/extraction scratch so
        # point queries cannot later grow the retained geometry unaccounted.
        for _, tri, _ in locators:
            if type(tri) is not Delaunay or tri._qhull is not None:
                raise TectonicsError('retained locator requires closed non-incremental Qhull')
            tri.transform
        seen = set()
        def retained(value):
            if id(value) in seen: return 0
            seen.add(id(value)); size = sys.getsizeof(value)
            if type(value) is np.ndarray:
                if value.dtype.hasobject:
                    raise TectonicsError('object arrays cannot back retained geometry')
                # __sizeof__ includes owned storage, but not a view's backing.
                return size+(retained(value.base) if value.base is not None else 0)
            if type(value) is Delaunay: return size+retained(vars(value))
            if type(value) is dict:
                return size+sum(retained(k)+retained(v) for k, v in value.items())
            if type(value) in (tuple, list): return size+sum(map(retained, value))
            if type(value) not in (bytes, str, int, float, bool, type(None)):
                raise TectonicsError('unaccounted retained locator backing')
            return size
        # _frozen makes compact bytes: include its array/base headers explicitly.
        # Each mesh pays for its complete locator, even when a wedge shares one;
        # closing either owner therefore never releases the other's reservation.
        allowance = sum(a.nbytes+512 for a in arrays.values())+retained(locators)+65536
        self._lease = budget.reserve(allowance, category='subduction-mesh-retained')
        self._lease.__enter__()
        try:
            self._arrays = {k: _frozen(v) for k, v in arrays.items()}
            self._locators = locators
        except BaseException:
            self._lease.__exit__(None, None, None); raise

    def _check(self, cancel=None):
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('closed or wrong-thread subduction mesh')
        _cancel(cancel)

    def _array(self, key):
        self._check(); return self._arrays[key].view()

    points = property(lambda self: self._array('points'))
    cells = property(lambda self: self._array('cells'))
    regions = property(lambda self: self._array('regions'))
    area = property(lambda self: self._array('area'))
    grad_lambda = property(lambda self: self._array('grad_lambda'))
    global_nodes = property(lambda self: self._array('global_nodes'))
    global_elements = property(lambda self: self._array('global_elements'))
    pressure_nodes = property(lambda self: self.points[:self.vertex_count])
    vertex_count = property(lambda self: self._vertex_count)
    spacing_km = property(lambda self: self._spacing)
    grading_id = property(lambda self: GRADINGS[self._grading])
    tip_target_m = property(lambda self: _target(50., 50., self._spacing, self._grading)*1000.)

    def wedge(self, *, cancel=None):
        self._check(cancel)
        selected = np.flatnonzero(self.regions == 2)
        if not len(selected):
            raise TectonicsError('mesh has no wedge')
        with self._budget.reserve(1024*len(selected)+128*len(self.points)+65536,
                                  category='subduction-wedge-extraction'):
            return self._wedge(selected, cancel)

    def _wedge(self, selected, cancel):
        cells = self.cells[selected]
        vertices = np.unique(cells[:, :3]); mids = np.unique(cells[:, 3:])
        nodes = np.concatenate((vertices, mids)); remap = np.full(len(self.points), -1, dtype=np.int64)
        remap[nodes] = np.arange(len(nodes))
        arrays = dict(points=self.points[nodes], cells=remap[cells], regions=self.regions[selected],
            area=self.area[selected], grad_lambda=self.grad_lambda[selected],
            global_nodes=self.global_nodes[nodes], global_elements=self.global_elements[selected])
        element_map = np.full(len(self.cells), -1, dtype=np.int64); element_map[selected] = np.arange(len(selected))
        locators = tuple((r, t, _frozen(element_map[m])) for r, t, m in self._locators if r == 2)
        self._check(cancel)
        return P2Mesh(arrays, len(vertices), locators, self.spacing_km, self._budget, self._grading)

    def locate(self, xy_km, *, region=None, cancel=None):
        self._check(cancel); shape = input_shape(xy_km)
        if len(shape) != 2 or shape[1] != 2 or not 1 <= shape[0] <= 65536:
            raise TectonicsError('bounded P by 2 point coordinates required')
        if region is not None and (type(region) is not int or region not in (0, 1, 2)):
            raise TectonicsError('region is 0 slab, 1 lid, or 2 wedge')
        with self._budget.reserve(512*shape[0]+65536, category='subduction-point-location'):
            q = read_array(xy_km, 'points in paper km')
            if np.any(q < 0.) or np.any(q[:, 0] > 660.) or np.any(q[:, 1] > 600.):
                raise TectonicsError('point is outside the subduction domain')
            result = np.full(len(q), -1, dtype=np.int64)
            for r, tri, mapping in self._locators:
                if region is not None and region != r:
                    continue
                inside = (q[:, 0] <= q[:, 1]) if r == 0 else (
                    (q[:, 0] >= q[:, 1]) & ((q[:, 1] <= 50.) if r == 1 else (q[:, 1] >= 50.)))
                use = np.flatnonzero((result < 0) & inside)
                if not len(use):
                    continue
                found = tri.find_simplex(q[use], tol=2e-11); valid = found >= 0
                result[use[valid]] = mapping[found[valid]]
            if np.any(result < 0):
                raise TectonicsError('point has no triangle on its requested one-sided region')
            offset = q-self.points[self.cells[result, 0]]
            b = np.einsum('pij,pj->pi', self.grad_lambda[result], offset); b[:, 0] += 1.
            if np.min(b) < -2e-11 or np.max(np.abs(b.sum(axis=1)-1.)) > 2e-13:
                raise TectonicsError('point-location barycentric verification failed')
            self._check(cancel); return result, b

    def interpolate(self, values, xy_km, *, region=None, cancel=None):
        self._check(cancel); shape = input_shape(values)
        if len(shape) not in (1, 2) or shape[0] != len(self.points) or (len(shape) == 2 and not 1 <= shape[1] <= 16):
            raise TectonicsError('P2 nodal scalar or bounded vector field required')
        query_shape = input_shape(xy_km)
        if len(query_shape) != 2 or query_shape[1] != 2 or not 1 <= query_shape[0] <= 65536:
            raise TectonicsError('bounded P by 2 point coordinates required')
        count = 1 if len(shape) == 1 else shape[1]
        scratch = 32*math.prod(shape)+query_shape[0]*(512+96*count)+65536
        with self._budget.reserve(scratch, category='subduction-interpolation'):
            v = read_array(values, 'P2 nodal values'); ids, b = self.locate(xy_km, region=region, cancel=cancel)
            # Pair each query with its own element, not an element-by-query product.
            n = np.column_stack([b[:, i]*(2*b[:, i]-1) for i in range(3)]+
                                [4*b[:, i]*b[:, j] for i, j in _EDGES])
            result = np.einsum('pi,pi...->p...', n, v[self.cells[ids]])
            self._check(cancel); return result

    def close(self):
        if self._closed:
            return
        self._check(); self._closed = True; self._arrays.clear(); self._locators = ()
        self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check(); return self

    def __exit__(self, *_):
        self.close()


def build_mesh(spacing_km, *, grading='interface-r3', budget=None, cancel=None):
    """Grade near slab/lid interfaces, merge exact shared vertices, add P2 edge nodes."""
    spacing = scalar(spacing_km, 'base mesh spacing km', positive=True)
    if not .05 <= spacing <= 200.:
        raise TectonicsError('mesh spacing outside bounded admission range')
    if not isinstance(grading, str) or grading not in GRADINGS:
        raise TectonicsError('explicit supported subduction mesh grading required')
    owner = WorkBudget(_CAP, parent=select_budget(budget))
    with owner.reserve(64*1024**2, category='subduction-mesh-build'):
        _cancel(cancel)
        segments = [_segment_points(a, b, spacing, cancel, grading) for a, b in _SEGMENTS]
        clouds = _interior_cloud(spacing, cancel, grading)
        vertices, vertex_map, triangles, regions, locators = [], {}, [], [], []
        region_hulls = []
        for region in range(3):
            _cancel(cancel)
            boundary = {p for i in _REGION_SEGMENTS[region] for p in segments[i]}
            local = np.asarray(sorted(boundary | set(clouds[region])), dtype=float)
            if len(vertex_map)+len(local) > 2*_MAX_VERTICES:
                raise TectonicsError('subduction mesh exceeds vertex admission')
            try:
                tri = Delaunay(local, qhull_options='Qbb Qc Qz Q12')
            except QhullError as exc:
                raise TectonicsError('subduction Delaunay construction failed without geometry repair') from exc
            if len(np.unique(tri.simplices)) != len(local) or len(tri.coplanar):
                raise TectonicsError('Delaunay omitted a supplied mesh point')
            _triangle_geometry(local, tri.simplices)
            local_ids = {tuple(p): i for i, p in enumerate(local)}
            expected = {tuple(sorted((local_ids[a], local_ids[b]))) for i in _REGION_SEGMENTS[region]
                        for a, b in zip(segments[i], segments[i][1:])}
            counts = _edge_counts(tri.simplices)
            if {edge for edge, n in counts.items() if n == 1} != expected:
                raise TectonicsError('Delaunay boundary differs from the shared interface partition')
            merge = []
            for p in local:
                key = tuple(p)
                if key not in vertex_map:
                    vertex_map[key] = len(vertices); vertices.append(key)
                merge.append(vertex_map[key])
            global_cells = np.asarray(merge, dtype=np.int64)[tri.simplices]
            offset = len(triangles); triangles.extend(global_cells); regions.extend([region]*len(global_cells))
            if len(triangles) > MAX_ELEMENTS or len(vertices) > _MAX_VERTICES:
                raise TectonicsError('subduction mesh exceeds 20000 triangles or vertex admission')
            locators.append((region, tri, _frozen(np.arange(offset, len(triangles)), np.int64)))
            region_hulls.append({tuple(sorted((merge[a], merge[b]))) for a, b in expected})
        for a, b, ids in ((0, 1, (0,)), (0, 2, (1,)), (1, 2, (6,))):
            expected = {tuple(sorted((vertex_map[p], vertex_map[q]))) for i in ids
                        for p, q in zip(segments[i], segments[i][1:])}
            if region_hulls[a] & region_hulls[b] != expected:
                raise TectonicsError('subduction interface edge mismatch')
        vertex_count = len(vertices); points = list(vertices); mids = {}; cells = []
        for t in triangles:
            _cancel(cancel); cell = list(t)
            for i, j in _EDGES:
                edge = tuple(sorted((int(t[i]), int(t[j]))))
                if edge not in mids:
                    mids[edge] = len(points)
                    points.append(tuple((x+y)/2 for x, y in zip(vertices[edge[0]], vertices[edge[1]])))
                cell.append(mids[edge])
            cells.append(cell)
        points = np.asarray(points); cells = np.asarray(cells, dtype=np.int64)
        area, gradients = _triangle_geometry(points, cells); region_array = np.asarray(regions, dtype=np.int64)
        expected_areas = (180000., 31750., 184250.)
        if any(abs(float(area[region_array == r].sum())-expected) > 1e-8 for r, expected in enumerate(expected_areas)):
            raise TectonicsError('subduction mesh does not cover each supplied region exactly')
        _edge_counts(cells)
        arrays = dict(points=points, cells=cells, regions=region_array, area=area, grad_lambda=gradients,
            global_nodes=np.arange(len(points), dtype=np.int64), global_elements=np.arange(len(cells), dtype=np.int64))
        _cancel(cancel); return P2Mesh(arrays, vertex_count, tuple(locators), spacing, owner, grading)
