"""Case-2a whole-wedge mechanical marking, not a goal-error certificate.

ASPECT-style Kelly velocity jumps and log-viscosity gradients, individually
max-normalised, maximum-merged, then a fixed 25% squared Dörfler bulk mark.
The analytic triangular log-viscosity gradient is an adaptation, not a literal
port of ASPECT's nodal derivative approximation. No diagnostic sample box is
used. Sources: geodynamics/aspect source/mesh_refinement/{velocity,viscosity}.cc
and aspect-documentation.readthedocs.io/en/latest/parameters/Mesh_20refinement.html.
"""
from __future__ import annotations

import weakref

import numpy as np

from atlas_tectonics._validation import TectonicsError, frozen, input_shape, read_array
from atlas_tectonics.constitutive import _cancel
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.subduction_mesh import P2Mesh, basis, quadrature


METHOD = 'aspect-style-mechanical-dorfler025-max-v2'
_CAP = 128*1024**2
_BATCH = 256


class _Metadata(dict):
    """Ordinary JSON-compatible dict with a retained-accounting lifetime."""
    __slots__ = ('__weakref__',)


def _retain(value, count, budget, category):
    lease = budget.reserve(count, category=category)
    lease.__enter__()
    try:
        # Attach array storage, not its reshape view: slices can outlive that view.
        target = value
        if isinstance(target, np.ndarray):
            while isinstance(target.base, np.ndarray):
                target = target.base
        weakref.finalize(target, lease.__exit__, None, None, None)
    except BaseException:
        lease.__exit__(None, None, None)
        raise
    return value


def _bulk(velocity, viscosity):
    """Stable element-order tie breaking; do not truncate an oversized mark."""
    if (not np.isfinite(velocity).all() or not np.isfinite(viscosity).all()
            or np.any(velocity < 0) or np.any(viscosity < 0)):
        raise TectonicsError('finite nonnegative refinement indicators required')
    vmax, emax = float(velocity.max()), float(viscosity.max())
    merged = np.maximum(velocity/vmax if vmax else velocity,
                        viscosity/emax if emax else viscosity)
    squared = merged**2
    total = float(squared.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64), vmax, emax, 0., 0.
    ranked = np.argsort(-squared, kind='stable')
    partial = np.cumsum(squared[ranked])
    count = int(np.searchsorted(partial, .25*total, side='left'))+1
    if count > 4096:
        raise MemoryLimitError('fixed bulk selection exceeds 4096 insertion points')
    return (ranked[:count], vmax, emax, float(partial[count-1]/total),
            0. if count == 1 else float(partial[count-2]/total))


def _face_gradient(mesh, elements, endpoints, s, velocity):
    cell = mesh.cells[elements]
    i = np.argmax(cell[:, :3] == endpoints[:, :1], axis=1)
    j = np.argmax(cell[:, :3] == endpoints[:, 1:], axis=1)
    bary = np.zeros((len(elements), len(s), 3))
    row, q = np.arange(len(elements))[:, None], np.arange(len(s))[None, :]
    bary[row, q, i[:, None]] = 1-s
    bary[row, q, j[:, None]] = s
    g = mesh.grad_lambda[elements]
    grad = np.empty((len(elements), len(s), 6, 2))
    for k in range(3):
        grad[:, :, k] = (4*bary[:, :, k, None]-1)*g[:, None, k]
    for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0)), 3):
        grad[:, :, k] = 4*(bary[:, :, a, None]*g[:, None, b]
                           + bary[:, :, b, None]*g[:, None, a])
    values = velocity[cell]
    magnitude = np.abs(values)+np.abs(values[:, :1])
    result = np.einsum('eni,eqnj->eqij', values-values[:, :1], grad)
    absolute_action = np.einsum('eni,eqnj->eqij', magnitude, np.abs(grad))
    return result, absolute_action


def _velocity_indicator(mesh, velocity, h, cancel):
    edges = np.concatenate([mesh.cells[:, pair] for pair in ((0, 1), (1, 2), (2, 0))])
    endpoints, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0,
                                          return_inverse=True, return_counts=True)
    if np.any(counts > 2):
        raise TectonicsError('nonmanifold wedge faces')
    order = np.argsort(inverse, kind='stable')
    starts = np.r_[0, np.cumsum(counts)[:-1]][counts == 2]
    faces = endpoints[counts == 2]
    cells = np.tile(np.arange(len(mesh.cells)), 3)
    left, right = cells[order[starts]], cells[order[starts+1]]
    s, weights = np.polynomial.legendre.leggauss(3)
    s, weights = (s+1)/2, weights/2
    squared = np.zeros(len(mesh.cells))
    for first in range(0, len(faces), _BATCH):
        _cancel(cancel)
        ids = slice(first, first+_BATCH)
        edge = faces[ids]
        tangent = mesh.points[edge[:, 1]]-mesh.points[edge[:, 0]]
        length = np.linalg.norm(tangent, axis=1)
        normal = np.column_stack((tangent[:, 1], -tangent[:, 0]))/length[:, None]
        gl, al = _face_gradient(mesh, left[ids], edge, s, velocity)
        gr, ar = _face_gradient(mesh, right[ids], edge, s, velocity)
        derivative = np.einsum('eqij,ej->eqi', gl-gr, normal)
        # Account subtraction, basis evaluation and the short dot products.
        # This is an input/operation-relative binary64 floor, not a physical
        # velocity tolerance. It prevents affine roundoff becoming a unit mark.
        floor = 128*np.finfo(float).eps*np.einsum('eqij,ej->eqi', al+ar, np.abs(normal))
        derivative = np.where(np.abs(derivative) <= floor, 0., derivative)
        integral = length*np.einsum('q,eqi,eqi->e', weights, derivative, derivative)
        np.add.at(squared, left[ids], integral)
        np.add.at(squared, right[ids], integral)
    return np.sqrt(h*squared)


def _viscosity_indicator(mesh, temperature, h, owner, cancel):
    # Runtime import allows subduction's orchestration to import this helper.
    from atlas_tectonics.subduction import benchmark_viscosity
    bary, weights = quadrature(6)
    result = np.empty(len(mesh.cells))
    for first in range(0, len(mesh.cells), _BATCH):
        _cancel(cancel)
        ids = slice(first, first+_BATCH)
        local = temperature[mesh.cells[ids]]
        n, g, _ = basis(bary, mesh.grad_lambda[ids], budget=owner, cancel=cancel)
        tq = np.einsum('qn,en->eq', n, local)
        gradient_t = np.einsum('en,eqnd->eqd', local-local[:, :1], g)
        eta = benchmark_viscosity('2a', tq, 0.)
        # eta = (1/eta_uncapped + 1/eta_cap)^-1; hence this exact derivative.
        gradient_log_eta = -(1-eta/1e26)[:, :, None]*335000/(8.3145*tq[:, :, None]**2)*gradient_t
        result[ids] = h[ids]**2*np.sqrt(
            np.einsum('q,eqd,eqd->e', weights, gradient_log_eta, gradient_log_eta))
    return result


def select_refinement_points(mesh, wedge, temperature_k, wedge_velocity_paper, *, budget, cancel=None):
    """Return immutable strict-interior km centroids and detached metadata.

    Only the case-2a diffusion law is supported: the caller must supply its
    converged global-node Kelvin field and wedge-local, slab-speed-unit velocity
    in paper x-right/y-down coordinates. No state, files or source inventory is
    read. Zero indicators return shape (0,2); the caller may retain its pilot.
    Inputs/geometry remain caller-owned. Work is released before return; result
    bytes and bounded metadata stay charged until their last owners are freed.
    """
    if not isinstance(budget, WorkBudget):
        raise TypeError('explicit WorkBudget required')
    if not isinstance(mesh, P2Mesh) or not isinstance(wedge, P2Mesh):
        raise TypeError('P2Mesh thermal and extracted wedge meshes required')
    mesh._check(cancel)
    wedge._check(cancel)
    if input_shape(temperature_k, 'temperature') != (len(mesh.points),):
        raise TectonicsError('temperature must use all thermal-mesh nodes')
    if input_shape(wedge_velocity_paper, 'velocity') != (len(wedge.points), 2):
        raise TectonicsError('velocity must use local wedge nodes in paper coordinates')
    owner = WorkBudget(_CAP, parent=budget)
    ne, nt, nv = len(wedge.cells), len(mesh.points), len(wedge.points)
    # Detached inputs, all unique/sort/topology/index arrays and their NumPy
    # sorting workspaces: <=1536 bytes/triangle. 4MiB additionally covers the
    # bounded 256-cell/face batches, returned basis arrays and Python overhead;
    # basis() separately charges its construction scratch through this owner.
    work_bytes = 1536*ne+16*nt+64*nv+4*1024**2
    with owner.reserve(work_bytes, category='subduction-refinement-work'):
        _cancel(cancel)
        nodes, elements = wedge.global_nodes, wedge.global_elements
        if (len(nodes) != nv or len(elements) != ne or np.any(nodes < 0)
                or np.any(nodes >= nt) or np.any(elements < 0)
                or np.any(elements >= len(mesh.cells))
                or not np.array_equal(elements, np.flatnonzero(mesh.regions == 2))
                or not np.all(wedge.regions == 2)
                or not np.array_equal(wedge.points, mesh.points[nodes])
                or not np.array_equal(nodes[wedge.cells], mesh.cells[elements])):
            raise TectonicsError('wedge must be the complete extraction of this thermal mesh')
        temperature = read_array(temperature_k, 'temperature')
        velocity = read_array(wedge_velocity_paper, 'velocity')
        if np.any(temperature <= 0):
            raise TectonicsError('positive Kelvin temperature required')
        vertices = wedge.points[wedge.cells[:, :3]]
        h = np.max(np.linalg.norm(vertices-np.roll(vertices, 1, axis=1), axis=2), axis=1)
        v = _velocity_indicator(wedge, velocity, h, cancel)
        e = _viscosity_indicator(wedge, temperature[nodes], h, owner, cancel)
        selected, vmax, emax, fraction, preceding = _bulk(v, e)
        points = vertices[selected].mean(axis=1)
        if (not np.all((points[:, 1] > 50.) & (points[:, 1] < points[:, 0])
                       & (points[:, 0] < 660.) & (points[:, 1] < 600.))
                or len(np.unique(points, axis=0)) != len(points)):
            raise TectonicsError('unique strictly interior wedge centroids required')
        _cancel(cancel)
        metadata = _Metadata(method=METHOD, case='2a', coordinate_system=mesh.coordinate_system,
            velocity_units='slab-speed units; x-right/y-down', spacing_km=mesh.spacing_km,
            geometry_id=mesh.geometry_id, wedge_geometry_id=wedge.geometry_id,
            selected_count=len(selected), wedge_elements=ne, bulk_squared_fraction=.25,
            achieved_squared_fraction=fraction, preceding_squared_fraction=preceding,
            velocity_normalisation_max=vmax, viscosity_normalisation_max=emax,
            normalisation='own whole-wedge maximum', combination='maximum',
            tie_break='baseline element index', selected_elements=selected.tolist(),
            selected_global_elements=elements[selected].tolist(),
            decision='refine' if len(selected) else 'zero-indicators',
            work_reservation_bytes=work_bytes, roundoff_guard='128eps absolute gradient action')
        # The work lease covers both immutable-copy construction and metadata
        # construction. Acquire retained leases before releasing that coverage.
        points = _retain(frozen(points), 512+points.nbytes, owner, 'subduction-refinement-points')
        metadata = _retain(metadata, 8192+128*len(selected), owner, 'subduction-refinement-metadata')
        return points, metadata
