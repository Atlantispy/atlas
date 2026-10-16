"""W01 3C: seeded, conforming initial planetary partitions, not plate dynamics.

An unweighted spherical Voronoi prior partitions the surface by nearest site.
For >=4 sites we use ONE native convex hull: outward face normals are shared
Voronoi junctions, and primal-edge incidence orders each dual cell. No per-plate
polygon clipping, coordinate welding, Qhull joggling, or raster approximation.
One, two and three-site diagrams have explicit spherical constructions.

Generated >=4-site candidates must surround the centre and be nondegenerate.
Whole-candidate rejection is bounded and recorded. This conditions the placement
prior; it is not an Earth plate distribution. Authored sites are NEVER resampled.
Working patch layout is downstream of the intrinsic partition, so triangulating
patches neither moves interplate edges nor changes their ownership.

Scientific status correction: this API generates a nearest-site GEOMETRY FIXTURE.
It is retained for exact mathematical regression and authored Voronoi cases, not
an accepted Earth-like plate-layout default. See plate_layout for a separately
identified reference-conditioned candidate and its deliberately open scientific
gates. No historical result identity or nearest-site expectation is changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import itertools
import json
import math
from typing import Mapping

import numpy as np

from .coordinates import SphericalFrame
from .geometry import GeometryError, _limits, _label, _json, _check_cancel
from ._validation import input_shape, read_array
from .resources import select_budget
from .spherical_geometry import SphericalChart
from .spherical_atlas import (SphericalAtlas, SphericalPatch, build_spherical_atlas,
                              _capture_directions, _unit)

_SCHEMA = 'atlas.planetary-partition.v1'
_METHOD = 'unweighted-spherical-voronoi-shared-dual-v1'
_RANDOM = 'shake256-le64-top53-sphere-v1'
# Conditioning/rejection floors, NOT snap distances or widened membership bands.
_SITE_SEPARATION = 1e-9
_DUAL_SEPARATION = 1e-10
_SPAN_MARGIN = 1e-10
_CHART_MARGIN = 1e-3


class PartitionCandidateError(GeometryError):
    """A candidate violates the declared generator's geometric validity domain."""


class PartitionGenerationError(GeometryError):
    """No accepted candidate within the requested finite attempt limit."""
    def __init__(self, attempts, rejections):
        self.attempts = attempts
        self.rejections = tuple(sorted(rejections.items()))
        super().__init__(f'no valid planetary partition after {attempts} candidates; '
                         f'rejections={dict(self.rejections)}')


@dataclass(frozen=True, slots=True)
class PlanetPartitionSettings:
    """Starting-layout settings only. No implicit radius, forces or terrain target.

    Seed is an unsigned 128-bit integer. Uniform surface candidates use a named
    byte/draw mapping independent of the global RNG and worker scheduling. The
    positive-spanning/nondegeneracy acceptance conditions bias accepted layouts,
    especially at four sites; that prior is recorded rather than hidden.
    """
    plate_count: int
    seed: int
    max_attempts: int = 128
    patch_layout: str = 'auto'

    def __post_init__(self):
        if type(self.plate_count) is not int or self.plate_count < 1:
            raise GeometryError('plate_count must be a positive integer')
        if type(self.seed) is not int or not 0 <= self.seed < 2**128:
            raise GeometryError('seed must be an unsigned 128-bit integer')
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 4096:
            raise GeometryError('max_attempts must be an integer in 1..4096')
        _layout(self.patch_layout)


def _layout(value):
    if type(value) is not str or value not in ('auto', 'triangles'):
        raise GeometryError('patch_layout must be auto or triangles')
    return value


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _preflight(count, limits):
    # Nondegenerate hull: F=2N-4, total Voronoi ring degree=6N-12.
    # Fan patches have three incidences per ring edge. Small diagrams are explicit.
    halfedges = max(108, 18*count)
    if count < 1 or halfedges > limits.max_vertices:
        raise GeometryError('projected planetary patch incidences exceed geometry limits')
    # Native hull/tree memory is an allowance, not a process-RSS guarantee.
    return 49152*count + 262144


def _draw_sites(seed, count, attempt):
    """Two 53-bit uniforms per stable site index; no mutable global PRNG state.

    z is uniform on [-1,1); longitude is uniform on [0,2*pi). This is uniform
    spherical area, unlike sampling latitude uniformly. Runtime trig rounding
    remains platform-dependent, so resolved site bytes and runtime are retained.
    """
    message = (_RANDOM.encode('ascii') + b'\0' + seed.to_bytes(16, 'little')
               + attempt.to_bytes(8, 'little'))
    words = np.frombuffer(hashlib.shake_256(message).digest(16*count), dtype='<u8')
    u = (words >> np.uint64(11)).astype('f8').reshape(count, 2) * (2.0**-53)
    z = 2*u[:, 0]-1
    angle = 2*math.pi*u[:, 1]
    radial = np.sqrt((1-z)*(1+z))
    return np.column_stack((radial*np.cos(angle), radial*np.sin(angle), z))


def _runtime():
    # Existing process-lifetime binary hash policy; no new runtime/cache framework.
    import scipy
    import scipy.spatial._qhull as qhull
    from .reuse import _loaded_binary, _file_hash
    from pathlib import Path
    return {'numpy': np.__version__, 'scipy': scipy.__version__,
            'qhull_binary_sha256': _loaded_binary(qhull.__file__),
            'generator_source_sha256': _file_hash(Path(__file__)),
            'qhull_options': 'Qc; Qt implicit; no QJ', 'random_mapping': _RANDOM,
            'reproducibility': 'resolved binary64 geometry; pinned-runtime repeatability'}


def _oriented_ring(ids, vertices, centre):
    """Choose orientation once; canonical start does not reverse the surface."""
    u = np.array([vertices[k] for k in ids])
    # Signed solid-angle fan. Sum of triangles uses stable differences for small cells.
    terms = []
    for a, b in zip(u, np.roll(u, -1, axis=0)):
        numerator = float(centre @ np.cross(a-centre, b-centre))
        denominator = 1+float(centre@a)+float(a@b)+float(b@centre)
        terms.append(2*math.atan2(numerator, denominator))
    area = math.fsum(terms)
    if not math.isfinite(area) or abs(area) <= 1e-24:
        raise PartitionCandidateError('unresolved-cell')
    ring = tuple(ids if area > 0 else tuple(reversed(ids)))
    start = ring.index(min(ring))
    return ring[start:]+ring[:start]


def _small_diagram(sites, names):
    """Exact nearest-site constructions for the low-rank 1..3-site cases.

    A hemisphere/lune has antipodal endpoints, so it is represented by several
    sub-hemispherical faces. Those added seams keep the SAME plate ownership.
    """
    n = len(names); vertices = {}; faces = []
    if n <= 2:
        axis = sites[0] if n == 1 else _unit(sites[0]-sites[1])
        helper = np.eye(3)[int(np.argmin(np.abs(axis)))]
        east = _unit(np.cross(helper, axis)); north = np.cross(axis, east)
        vertices = {'pole+': axis, 'pole-': -axis,
                    'equator0': east, 'equator1': north,
                    'equator2': -east, 'equator3': -north}
        for side in range(2):
            for k in range(4):
                ids = ('pole+' if side == 0 else 'pole-', f'equator{k}', f'equator{(k+1)%4}')
                centre = _unit(sum(vertices[x] for x in ids))
                faces.append((names[0 if n == 1 else side], ids, tuple(centre)))
    else:
        raw = np.cross(sites[1]-sites[0], sites[2]-sites[0])
        if np.linalg.norm(raw) < _DUAL_SEPARATION:
            raise PartitionCandidateError('degenerate-three-site-diagram')
        pole = _unit(raw)
        if pole[int(np.argmax(np.abs(pole)))] < 0: pole = -pole
        vertices.update({'pole+': pole, 'pole-': -pole})
        mids = {}
        for i, j in itertools.combinations(range(3), 2):
            k = 3-i-j
            mid = _unit(np.cross(pole, sites[i]-sites[j]))
            margin = float(mid @ (sites[i]-sites[k]))
            if abs(margin) < _DUAL_SEPARATION:
                raise PartitionCandidateError('ambiguous-three-site-edge')
            if margin < 0: mid = -mid
            key = f'edge-{i}-{j}'; vertices[key] = mid; mids[(i, j)] = key
        for i, name in enumerate(names):
            centre = _unit(sites[i]-float(sites[i]@pole)*pole)
            anchor = f'centre-{i}'; vertices[anchor] = centre
            others = [j for j in range(3) if j != i]
            rim = ('pole+', mids[tuple(sorted((i, others[0])))],
                   'pole-', mids[tuple(sorted((i, others[1])))])
            for a, b in zip(rim, rim[1:]+rim[:1]):
                ids = (anchor, a, b)
                faces.append((name, ids, tuple(_unit(sum(vertices[x] for x in ids)))))
    return vertices, faces


def _dual_diagram(sites, names, cancel):
    """One native hull + linear-size incidence traversal; no N-by-N matrix.

    A hull triangle's outward normal is a spherical Voronoi junction. An edge
    belongs to exactly two hull triangles: it therefore defines ONE shared dual
    edge, simultaneously used by its two site cells. Incidence, not atan sorting,
    establishes ring order. Geometrically ambiguous cofacets are refused, not moved.
    """
    from scipy.spatial import ConvexHull, QhullError, cKDTree
    try:
        hull = ConvexHull(sites, qhull_options='Qc')
    except QhullError as exc:
        raise PartitionCandidateError('degenerate-hull') from exc
    _check_cancel(cancel)
    if len(hull.vertices) != len(sites) or len(hull.coplanar):
        raise PartitionCandidateError('omitted-hull-site')
    if np.any(-hull.equations[:, 3] <= _SPAN_MARGIN):
        raise PartitionCandidateError('sites-do-not-strictly-surround-centre')
    triples = [tuple(sorted(int(i) for i in face)) for face in hull.simplices]
    order = sorted(range(len(triples)), key=triples.__getitem__)
    normals = _capture_directions(hull.equations[order, :3])
    if np.min(cKDTree(normals).query(normals, k=2, workers=1)[0][:, 1]) <= _DUAL_SEPARATION:
        raise PartitionCandidateError('ambiguous-cofacets')
    triples = [triples[i] for i in order]
    vertex_names = tuple('junction-'+_digest([names[i] for i in t]) for t in triples)
    vertices = dict(zip(vertex_names, normals))
    primal = {}; fans = [dict() for _ in sites]
    for f, triple in enumerate(triples):
        if f % 1024 == 0: _check_cancel(cancel)
        for i, j in itertools.combinations(triple, 2):
            primal.setdefault((i, j), []).append(f)
    for (i, j), use in primal.items():
        if len(use) != 2: raise PartitionCandidateError('nonmanifold-hull')
        a, b = use
        for site in (i, j):
            fans[site].setdefault(a, []).append(b)
            fans[site].setdefault(b, []).append(a)
    faces = []
    for site, adjacent in enumerate(fans):
        _check_cancel(cancel)
        if len(adjacent) < 3 or any(len(v) != 2 for v in adjacent.values()):
            raise PartitionCandidateError('invalid-dual-fan')
        start = min(adjacent); ring = [start]; visited = {start}; previous = -1; current = start
        while True:
            choices = sorted(adjacent[current])
            following = choices[0] if choices[0] != previous else choices[1]
            if following == start: break
            if following in visited or len(ring) >= len(adjacent):
                raise PartitionCandidateError('non-simple-dual-cycle')
            ring.append(following); visited.add(following); previous, current = current, following
        if len(ring) != len(adjacent): raise PartitionCandidateError('disconnected-dual-cycle')
        faces.append((names[site], tuple(vertex_names[f] for f in ring), tuple(sites[site])))
    return vertices, faces


@dataclass(frozen=True, slots=True, init=False)
class PlanetaryPartitionPlan:
    """Immutable generated topology; reusable across different working-patch layouts.

    Site, vertex and face data are prepared once. build() derives auto/fan patches,
    then invokes the EXISTING independent stage-3B closed-manifold validator.
    Retained bytes belong to the caller. No cache directory, global pool or mutable
    random state is created. The plan's identity excludes working charts/layout.
    """
    sphere: SphericalFrame
    plate_ids: tuple[str, ...]
    vertex_ids: tuple[str, ...]
    partition_id: str
    _sites: bytes = field(repr=False)
    _vertices: bytes = field(repr=False)
    _faces: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise GeometryError('use prepare_planetary_partition()')

    @property
    def site_directions(self): return np.frombuffer(self._sites, dtype='f8').reshape(-1, 3)
    @property
    def vertex_directions(self): return np.frombuffer(self._vertices, dtype='f8').reshape(-1, 3)
    @property
    def retained_bytes_estimate(self):
        return len(self._sites)+len(self._vertices)+len(self._faces)+512*(len(self.plate_ids)+len(self.vertex_ids))

    def __deepcopy__(self, memo): memo[id(self)] = self; return self
    def __reduce__(self):
        # Do not trust restored mutable arrays or reuse an unvalidated derived hull.
        return (_restore_plan, (self.sphere, self.plate_ids, self._sites, self.partition_id))

    def build(self, *, patch_layout='auto', limits=None, budget=None, cancel=None, provenance=None):
        """Derive charts/patches without changing sites or interplate geometry.

        auto retains a whole cell whenever its site-centred chart is conditioned.
        triangles fans the same cell to interior points. Fan spokes are patch
        seams only. No edge is resampled and no junction is duplicated per owner.
        """
        _check_cancel(cancel); _layout(patch_layout); lim = _limits(limits)
        policy = select_budget(budget); count = len(self.plate_ids)
        estimate = _preflight(count, lim)
        with policy.reserve(estimate, category='partition-patches'):
            vertices = dict(zip(self.vertex_ids, self.vertex_directions))
            faces = json.loads(self._faces)
            patches = []
            for i, (owner, ring, centre) in enumerate(faces):
                _check_cancel(cancel); ring = tuple(ring)
                points = np.array([vertices[v] for v in ring])
                centre = np.array(centre)
                identity = 'patch-'+str(i).zfill(8)
                if patch_layout == 'auto' and np.min(points@centre) >= _CHART_MARGIN:
                    chart = SphericalChart(self.sphere, tuple(centre), _CHART_MARGIN)
                    patches.append(SphericalPatch(identity, owner, owner, ring, chart))
                else:
                    anchor = 'fan-'+_digest((owner, ring))
                    vertices[anchor] = centre
                    for j, (a, b) in enumerate(zip(ring, ring[1:]+ring[:1])):
                        tri = (a, b, anchor)
                        c = _unit(vertices[a]+vertices[b]+centre)
                        if min(float(vertices[v]@c) for v in tri) < _CHART_MARGIN:
                            raise PartitionCandidateError('unconditioned-triangle')
                        chart = SphericalChart(self.sphere, tuple(c), _CHART_MARGIN)
                        patches.append(SphericalPatch(identity+f'-{j}', owner, owner, tri, chart))
            # Only vertices present in the chosen representation are retained.
            used = {v for p in patches for v in p.vertex_ids}
            vertices = {v: vertices[v] for v in sorted(used)}
            origin = {'route': 'authored-sites'} if provenance is None else provenance
            source = {'schema': _SCHEMA, 'method': _METHOD, 'partition_id': self.partition_id,
                'site_ids': list(self.plate_ids), 'site_directions': self.site_directions.tolist(),
                'patch_layout': patch_layout, 'generation': origin, 'runtime': _runtime(),
                'prior': 'nearest angular site; >=4 sites conditioned on spanning and nondegeneracy',
                'physical_validation': False}
            # All guards (pairing, junction links, connectedness, Euler and area)
            # stay enabled, even though construction is shared by design.
            return build_spherical_atlas(self.sphere, vertices, tuple(patches), limits=lim,
                    budget=policy, cancel=cancel, source_bindings={'partition_generation': source})


def prepare_planetary_partition(sphere, sites, *, limits=None, budget=None, cancel=None):
    """Prepare nearest-site topology from an explicit site mapping, without RNG.

    Caller-authored sites are preserved as directions; no random replacement,
    smoothing, jitter or desired-mountain fitting is ever applied. Non-spanning
    >=4-site sets and unresolved degeneracies are explicit unsupported inputs.
    Existing authored stage-3B atlas construction remains available unchanged.
    """
    _check_cancel(cancel); lim = _limits(limits); policy = select_budget(budget)
    if type(sphere) is not SphericalFrame or not isinstance(sites, Mapping):
        raise GeometryError('explicit SphericalFrame and site mapping required')
    estimate = _preflight(len(sites), lim)
    with policy.reserve(estimate, category='partition-topology'):
        for name in sites: _label(name, 'plate ID')
        names = tuple(sorted(sites))
        points = np.empty((len(names), 3), dtype='f8')
        for i, name in enumerate(names):
            _check_cancel(cancel)
            if input_shape(sites[name], 'site') != (3,): raise GeometryError('one 3D direction per site')
            points[i] = read_array(sites[name], 'site')
        points = _capture_directions(points)
        if len(names) > 1:
            from scipy.spatial import cKDTree
            nearest = cKDTree(points).query(points, k=2, workers=1)[0][:, 1]
            if np.min(nearest) <= _SITE_SEPARATION:
                raise PartitionCandidateError('duplicate-or-unresolved-sites')
        vertices, faces = (_small_diagram(points, names) if len(names) < 4
                            else _dual_diagram(points, names, cancel))
        ordered = []
        for owner, ring, centre in faces:
            ring = _oriented_ring(tuple(ring), vertices, np.asarray(centre))
            ordered.append((owner, ring, centre))
        ordered.sort(key=lambda f: (f[0], f[1]))
        vertex_ids = tuple(sorted(vertices))
        vertex_data = _capture_directions(np.array([vertices[v] for v in vertex_ids]))
        payload = _json(ordered)
        identity = hashlib.sha256(_json({'schema': _SCHEMA, 'method': _METHOD,
            'sphere': sphere.descriptor(), 'plates': names, 'vertices': vertex_ids,
            'faces': ordered})+b'\0'+points.tobytes()+b'\0'+vertex_data.tobytes()).hexdigest()
        obj = object.__new__(PlanetaryPartitionPlan)
        for k, value in {'sphere': sphere, 'plate_ids': names, 'vertex_ids': vertex_ids,
            'partition_id': identity, '_sites': points.tobytes(), '_vertices': vertex_data.tobytes(),
            '_faces': payload}.items(): object.__setattr__(obj, k, value)
        _check_cancel(cancel)
        return obj


def _restore_plan(sphere, ids, payload, identity):
    if type(ids) is not tuple or type(payload) is not bytes or len(payload) != 24*len(ids):
        raise GeometryError('invalid partition plan payload')
    if ids != tuple(sorted(set(ids))): raise GeometryError('invalid partition site IDs')
    plan = prepare_planetary_partition(sphere, dict(zip(ids, np.frombuffer(payload, dtype='f8').reshape(-1, 3))))
    if plan.partition_id != identity: raise GeometryError('restored partition plan identity mismatch')
    return plan


def generate_planetary_partition(sphere, settings, *, limits=None, budget=None, cancel=None):
    """Generate, build and validate one complete spherical initial configuration.

    Candidate sites are sampled before any patch decisions. Rejections restart a
    complete labelled candidate and are recorded. A budget failure/cancellation or
    a final atlas validator failure is NOT interpreted as permission to reroll.
    No evolution, terrain target, property calibration, remote write or I/O occurs.
    """
    _check_cancel(cancel); lim = _limits(limits); policy = select_budget(budget)
    if type(settings) is not PlanetPartitionSettings or type(sphere) is not SphericalFrame:
        raise GeometryError('explicit sphere and PlanetPartitionSettings required')
    count = settings.plate_count; _preflight(count, lim)
    # Reject unreasonable allocation before asking SHAKE or a native library for it.
    with policy.reserve(512*count+65536, category='partition-seeds'):
        names = tuple(f'plate-{i:06d}' for i in range(count))
        rejected = {}
        for attempt in range(settings.max_attempts):
            _check_cancel(cancel)
            sites = _draw_sites(settings.seed, count, attempt)
            plan = None
            try:
                plan = prepare_planetary_partition(sphere, dict(zip(names, sites)),
                               limits=lim, budget=policy, cancel=cancel)
                with policy.reserve(plan.retained_bytes_estimate, category='partition-plan-retained'):
                    provenance = {'route': 'seeded', 'settings': asdict(settings),
                        'accepted_attempt': attempt, 'candidate_count': attempt+1,
                        'rejections': dict(sorted(rejected.items())), 'random_mapping': _RANDOM}
                    atlas = plan.build(patch_layout=settings.patch_layout, limits=lim,
                                       budget=policy, cancel=cancel, provenance=provenance)
                return atlas
            except PartitionCandidateError as exc:
                reason = str(exc); rejected[reason] = rejected.get(reason, 0)+1
                # Do not keep a rejected plan alive into the next candidate.
                plan = None
        raise PartitionGenerationError(settings.max_attempts, rejected)


def generated_partition_id(atlas):
    """Intrinsic prepared-partition ID, not the working-patch atlas identity."""
    return _generation(atlas)['partition_id']


def _generation(atlas):
    if type(atlas) is not SphericalAtlas: raise GeometryError('SphericalAtlas required')
    source = atlas.descriptor()['source_bindings'].get('partition_generation')
    expected = {'schema','method','partition_id','site_ids','site_directions','patch_layout',
                'generation','runtime','prior','physical_validation'}
    if type(source) is not dict or set(source) != expected or source['schema'] != _SCHEMA or source['method'] != _METHOD:
        raise GeometryError('atlas has no compatible partition-generation definition')
    ids = source['site_ids']; values = source['site_directions']; identity = source['partition_id']
    if (type(ids) is not list or tuple(ids) != atlas.plate_ids or
            type(values) is not list or input_shape(values, 'saved sites') != (len(ids), 3) or
            type(identity) is not str or len(identity) != 64 or
            any(c not in '0123456789abcdef' for c in identity) or
            source['physical_validation'] is not False):
        raise GeometryError('invalid partition-generation inventory')
    _layout(source['patch_layout'])
    return source


def repatch_planetary_partition(atlas, *, patch_layout='triangles', limits=None, budget=None, cancel=None):
    """Regenerate ONLY working patches from saved sites; do not draw another world.

    Authored arbitrary atlases remain authored and are refused by this specialised
    route. The prepared-plan API is preferable for repeated in-process layouts.
    Full saved atlases use existing save/load_spherical_atlas(), not this rebuild.
    """
    _check_cancel(cancel); source = _generation(atlas); _layout(patch_layout)
    sites = dict(zip(source['site_ids'], source['site_directions']))
    plan = prepare_planetary_partition(atlas.sphere, sites, limits=limits, budget=budget, cancel=cancel)
    if plan.partition_id != source['partition_id']:
        raise GeometryError('reconstructed partition differs; no silent geometry migration')
    with select_budget(budget).reserve(plan.retained_bytes_estimate, category='partition-plan-retained'):
        return plan.build(patch_layout=patch_layout, limits=limits, budget=budget,
                          cancel=cancel, provenance=source['generation'])
