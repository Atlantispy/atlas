"""Conservative P2 thermal velocity as the curl of a continuous P3 potential.

Minimise integral |curl(psi)-v_mechanical|^2 with fixed boundary psi. On affine
triangles, C0 P3 psi gives locally divergence-free P2 velocity and a continuous
normal trace; tangential velocity is not constrained or promised. The original
mechanical field remains separate. Coordinates/velocity units are those of the
mesh/input (paper x right, y down, km); curl(psi)=(psi_y,-psi_x).

Method basis: J. Schoeberl, H(div)-based FEM, normal continuity and BDM spaces:
https://jschoeberl.github.io/talk-HDivconforming/theory/spacehdiv.html
Chang, Azevedo and Batty (2019), DOI 10.1145/3309486.3339890, curl-based
divergence-free velocity reconstruction (not their grid interpolation algorithm).
This implementation derives the P3 constrained L2 fit directly; it is neither
their solver nor a modification of the mechanical pressure/velocity solution.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import threading

import numpy as np
import scipy
from scipy import sparse
from scipy.sparse.linalg import splu

from ._validation import TectonicsError, input_shape, read_array
from .constitutive import _cancel
from .resources import WorkBudget, select_budget
from .stokes_execution import _native_lease
from .subduction_mesh import P2Mesh, MAX_ELEMENTS, basis, quadrature


_EDGES = ((0, 1), (1, 2), (2, 0))
_P2_BARY = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                     [.5, .5, 0.], [0., .5, .5], [.5, 0., .5]])
_CAP = 128*1024**2
_ROUND = float(128*np.finfo(float).eps)
_BATCH = 128


def _frozen(value, dtype=None):
    value = np.asarray(value, dtype=dtype)
    return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)


def _json(record): return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _p3_derivatives(bary):
    """Derivative with respect to the three barycentric coordinates, Q x 10 x 3."""
    b = np.asarray(bary); result = np.zeros((len(b), 10, 3))
    for i in range(3): result[:, i, i] = 13.5*b[:, i]**2-9*b[:, i]+1.
    for edge, (i, j) in enumerate(_EDGES):
        near_i, near_j = 3+2*edge, 4+2*edge
        result[:, near_i, i] = 4.5*b[:, j]*(6*b[:, i]-1)
        result[:, near_i, j] = 4.5*b[:, i]*(3*b[:, i]-1)
        result[:, near_j, j] = 4.5*b[:, i]*(6*b[:, j]-1)
        result[:, near_j, i] = 4.5*b[:, j]*(3*b[:, j]-1)
    for i in range(3): result[:, 9, i] = 27*b[:, (i+1) % 3]*b[:, (i+2) % 3]
    return result


def _gradient(derivative, grad_lambda):
    return np.einsum('qni,eij->eqnj', derivative, grad_lambda, optimize=True)


def _potential_gradient(derivative, grad_lambda, local_potential):
    """Differentiate local nodal differences, not an arbitrary global gauge.

    Lagrange bases partition unity, so sum(grad N_i) is zero and subtracting
    psi_0 leaves the same polynomial gradient. Removing that null component
    before multiplication avoids cancellation of O(psi_gauge/h) terms on tiny
    elements; no trace, coefficient or acceptance tolerance is changed.
    """
    relative = local_potential-local_potential[:, :1]
    return np.einsum('eqnd,en->eqd', _gradient(derivative, grad_lambda), relative,
                     optimize=True)


def _partial_integrals(t):
    """Integrals from 0 to t of P2 edge bases at endpoint, midpoint, endpoint."""
    return np.array([2*t**3/3-1.5*t*t+t, 2*t*t-4*t**3/3, 2*t**3/3-.5*t*t])


@dataclass(frozen=True, slots=True)
class ConservativeVelocityResult:
    plan_id: str
    result_id: str
    elements: int
    _velocity: bytes = field(repr=False)
    _potential: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    @property
    def element_node_velocity(self): return np.frombuffer(self._velocity, np.float64).reshape(self.elements, 6, 2)
    @property
    def velocity(self): return self.element_node_velocity
    @property
    def streamfunction(self): return np.frombuffer(self._potential, np.float64)
    @property
    def nbytes(self): return len(self._velocity)+len(self._potential)+len(self._record)
    def diagnostics(self): return json.loads(self._record)
    def statistics(self): return self.diagnostics()


class PreparedSubductionTransport:
    """Reusable scalar SPD operator; factorisation is lazy and releasable.

    Input is one simply connected conforming P2 wedge mesh. Keep its owner open.
    Integrated-input mode preserves the complete P2 normal trace on every outer
    edge by exact cubic antiderivatives; incompatible net boundary flux refuses.
    An explicit boundary_streamfunction(xy) instead supplies the boundary authority,
    useful for analytic case 1a. Its P3 nodal trace replaces sampled P2 normals;
    that difference is reported, never passed off as preserving those normals.
    Call release_factor() before another large mechanical/thermal factor. Sparse
    geometry/matrix leases survive that release until close(). Caller accounts for
    returned result lifetime. Budget allowances are not native-allocator RSS caps.
    """
    def __init__(self, mesh, *, budget=None, cancel=None):
        if type(mesh) is not P2Mesh: raise TectonicsError('explicit P2Mesh required for thermal velocity transfer')
        mesh._check(cancel)
        if not 1 <= len(mesh.cells) <= MAX_ELEMENTS or np.any(mesh.regions != 2):
            raise TectonicsError('bounded wedge-only P2 mesh required')
        self._owner = threading.get_ident(); self._closed = False; self._active = False
        self.mesh = mesh; self.budget = WorkBudget(_CAP, parent=select_budget(budget))
        self._factor = None; self._factor_lease = None; self._factorisations = 0
        e = len(mesh.cells)
        self._lease = self.budget.reserve(4000*e+256*len(mesh.points)+65536,
                                         category='subduction-transport-retained')
        self._lease.__enter__()
        try:
            with _native_lease(), self.budget.reserve(4000*e+1024**2,
                    category='subduction-transport-assembly'):
                self._prepare(mesh, cancel)
            # Construction dictionaries/COO buffers have now gone out of scope.
            # Charge the actual owned backing storage and explicit object overhead,
            # while retaining the old envelope until the replacement is admitted.
            self.retained_payload_bytes, self.retained_allowance_bytes = self._retained_storage()
            compact = self.budget.reserve(self.retained_allowance_bytes,
                                          category='subduction-transport-retained')
            compact.__enter__()
            construction = self._lease; self._lease = compact
            construction.__exit__(None, None, None)
            self._check(cancel)
        except BaseException:
            self._lease.__exit__(None, None, None); self._closed = True; raise

    def _prepare(self, mesh, cancel):
        vertices = mesh.points[:mesh.vertex_count]; cells = mesh.cells
        points = list(map(tuple, vertices)); entries = {}; p3 = np.empty((len(cells), 10), np.int64)
        p3[:, :3] = cells[:, :3]
        for element, cell in enumerate(cells):
            _cancel(cancel)
            for edge, (i, j) in enumerate(_EDGES):
                a, b = int(cell[i]), int(cell[j]); key = tuple(sorted((a, b)))
                if key not in entries:
                    lo, hi = key; first = len(points)
                    points.extend((tuple((2*vertices[lo]+vertices[hi])/3),
                                   tuple((vertices[lo]+2*vertices[hi])/3)))
                    entries[key] = (first, [])
                first, incidence = entries[key]
                incidence.append((element, edge, a, b))
                if len(incidence) > 2: raise TectonicsError('nonmanifold thermal-transfer edge')
                p3[element, 3+2*edge:5+2*edge] = (first, first+1) if a < b else (first+1, first)
            p3[element, 9] = len(points); points.append(tuple(vertices[cell[:3]].mean(axis=0)))
        boundary = []; interior = []; outgoing = {}
        for first, incidence in entries.values():
            if len(incidence) == 1:
                element, edge, a, b = incidence[0]
                if a in outgoing: raise TectonicsError('branched thermal-transfer boundary')
                outgoing[a] = (b, element, edge)
            else:
                (e0, edge0, a0, b0), (e1, edge1, a1, b1) = incidence
                if (a0, b0) != (b1, a1): raise TectonicsError('inconsistent oriented thermal-transfer mesh')
                i, j = _EDGES[edge0]; u, v = _EDGES[edge1]
                interior.append((e0, i, j, edge0+3, e1, v, u, edge1+3))
        if not outgoing: raise TectonicsError('thermal-transfer domain has no boundary')
        # Close the integrated potential over the longest edge, never an
        # arbitrarily numbered tiny corner edge. The continuum integral changes
        # only by a constant gauge; its accepted round-off-sized closure defect
        # is then differentiated over the best-conditioned available length.
        # Nothing is subtracted from or redistributed among the input fluxes.
        closing = max(outgoing, key=lambda a: (
            float(np.linalg.norm(vertices[outgoing[a][0]]-vertices[a])), -a))
        initial = current = outgoing[closing][0]; seen = set()
        while current not in seen:
            seen.add(current)
            if current not in outgoing: raise TectonicsError('open thermal-transfer boundary')
            following, element, edge = outgoing[current]
            boundary.append((element, edge)); current = following
        if current != initial or len(seen) != len(outgoing):
            raise TectonicsError('thermal transfer requires one simply connected boundary component')
        self._cells = _frozen(p3); self._points = _frozen(points)
        self._boundary = tuple(boundary); self._interior = _frozen(interior, np.int64).reshape(-1, 8)
        fixed = set()
        for element, edge in boundary:
            i, j = _EDGES[edge]
            fixed.update(map(int, p3[element, [i, j, 3+2*edge, 4+2*edge]]))
        self._fixed = _frozen(sorted(fixed), np.int64)
        self._free = _frozen(np.setdiff1d(np.arange(len(points)), self._fixed), np.int64)
        self._bary, self._weights = quadrature(degree=6)
        self._p2 = basis(self._bary)
        self._dq = _frozen(_p3_derivatives(self._bary)); self._dn = _frozen(_p3_derivatives(_P2_BARY))
        local = np.empty((len(cells), 10, 10))
        for start in range(0, len(cells), _BATCH):
            _cancel(cancel); end = min(start+_BATCH, len(cells))
            gradient = _gradient(self._dq, mesh.grad_lambda[start:end])
            local[start:end] = np.einsum('eqnd,eqmd,q,e->enm', gradient, gradient,
                self._weights, mesh.area[start:end], optimize=True)
        rows = np.broadcast_to(p3[:, :, None], local.shape).ravel()
        cols = np.broadcast_to(p3[:, None, :], local.shape).ravel()
        matrix = sparse.coo_matrix((local.ravel(), (rows, cols)), shape=(len(points), len(points))).tocsr()
        self._matrix = matrix[self._free][:, self._free].tocsr()
        self._boundary_matrix = matrix[self._free][:, self._fixed].tocsr()
        if np.any(self._matrix.diagonal() <= 0): raise TectonicsError('invalid scalar thermal-transfer stiffness')
        record = dict(method='atlas.w08-p3-streamfunction-transfer.v3', elements=len(cells),
            p3_nodes=len(points), free_nodes=len(self._free), boundary_nodes=len(self._fixed),
            quadrature_degree=6, numpy=np.__version__, scipy=scipy.__version__,
            coordinates=mesh.coordinate_system, boundary='single-oriented-component-longest-edge-closure')
        digest = hashlib.sha256(_json(record))
        for array in (mesh.points, cells, mesh.area, mesh.grad_lambda): digest.update(array.tobytes())
        self.plan_id = digest.hexdigest()

    def _retained_storage(self):
        """Owned backing capacity, not only visible slices; shared mesh excluded.

        The mesh has its own live owner/lease. Sparse factors and evaluation
        scratch also keep their separate admissions. NumPy descriptor/base-chain
        and sparse/Python metadata overhead is reserved explicitly in addition to
        the complete distinct retained array/bytes allocations.
        """
        arrays = [self._cells, self._points, self._interior, self._fixed, self._free,
                  self._bary, self._weights, self._p2, self._dq, self._dn]
        arrays.extend(a for matrix in (self._matrix, self._boundary_matrix)
                      for a in (matrix.data, matrix.indices, matrix.indptr))
        backing = {}; descriptors = set()
        for array in arrays:
            owner = array
            while isinstance(owner, np.ndarray):
                descriptors.add(id(owner))
                if owner.base is None:
                    backing[id(owner)] = owner.nbytes
                    break
                owner = owner.base
            else:
                if isinstance(owner, bytes): backing[id(owner)] = len(owner)
                elif isinstance(owner, memoryview): backing[id(owner.obj)] = owner.nbytes
                else: raise TectonicsError('unaccounted thermal-transfer array backing owner')
        payload = sum(backing.values())
        # 512 per ndarray descriptor/base and sparse descriptor; 192 per retained
        # oriented boundary pair (tuple, two ints and parent pointer); 32KiB for
        # the owner, dictionaries, small scalar/identity metadata and allocator
        # bookkeeping. Payload owners include their full capacity above.
        overhead = 32768+512*(len(descriptors)+2)+192*len(self._boundary)
        return payload, payload+overhead

    def _check(self, cancel=None):
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('closed or wrong-thread thermal velocity transfer')
        self.mesh._check(cancel)

    @contextmanager
    def _operation(self, cancel):
        self._check(cancel)
        if self._active: raise TectonicsError('thermal velocity transfer is already active')
        self._active = True
        try:
            with _native_lease(): yield
            _cancel(cancel)
        finally: self._active = False

    def _get_factor(self, cancel):
        if self._factor is not None: return self._factor
        _cancel(cancel); n, nnz = self._matrix.shape[0], self._matrix.nnz
        if not n: return None
        # Explicit bounded scalar-factor admission, coordinated with the root's
        # sequential flow/transfer/heat phases. Actual retained fill still gates
        # publication; this cap is not an allocator-enforced RSS guarantee.
        allowance = min(64*1024**2, int(20*n**1.5+48*nnz+1024**2))
        lease = self.budget.reserve(allowance, category='subduction-transport-factor'); lease.__enter__()
        try:
            factor = splu(self._matrix.tocsc(), permc_spec='MMD_AT_PLUS_A',
                          diag_pivot_thresh=0., options={'SymmetricMode': True})
            actual = sum(a.nbytes for m in (factor.L, factor.U) for a in (m.data, m.indices, m.indptr))
            if 3*actual+self._matrix.data.nbytes > allowance:
                raise TectonicsError('scalar thermal-transfer factor exceeds admitted fill')
            _cancel(cancel)
            self._factor = factor; self._factor_lease = lease; self._factorisations += 1
            return factor
        except BaseException:
            lease.__exit__(None, None, None); raise

    def _boundary_values(self, velocity, analytic, cancel):
        full = np.zeros(len(self._points)); increments = []; absolute = []
        gauge_edge = 0; shortest_squared = math.inf
        # One consistent traversal: cell orientation is positive in the numerical
        # x/y coordinates, so (dy,-dx) is the outward normal times edge length.
        for edge_index, (element, edge) in enumerate(self._boundary):
            _cancel(cancel); i, j = _EDGES[edge]
            xy = self.mesh.points[self.mesh.cells[element, [i, j]]]
            tangent = xy[1]-xy[0]; normal_length = np.array([tangent[1], -tangent[0]])
            length_squared = float(tangent@tangent)
            if length_squared < shortest_squared:
                gauge_edge, shortest_squared = edge_index, length_squared
            trace = velocity[element, [i, edge+3, j]]@normal_length
            increments.append(math.fsum((float(trace[0])/6, 2*float(trace[1])/3, float(trace[2])/6)))
            absolute.extend((abs(float(trace[0]))/6, 2*abs(float(trace[1]))/3, abs(float(trace[2]))/6))
        net = math.fsum(increments); flux_scale = math.fsum(absolute)
        if not math.isfinite(net) or not math.isfinite(flux_scale):
            raise TectonicsError('thermal-transfer boundary flux exceeds numerical range')
        if analytic is not None:
            if not callable(analytic): raise TectonicsError('boundary_streamfunction must be an explicit callable')
            given = read_array(analytic(self._points[self._fixed]), 'analytic boundary streamfunction')
            if given.shape != (len(self._fixed),): raise TectonicsError('boundary streamfunction needs one value per requested point')
            full[self._fixed] = given-given[0]
            return full, net, flux_scale, 'explicit-streamfunction'
        if abs(net) > _ROUND*flux_scale:
            raise TectonicsError('input P2 boundary has incompatible net material flux; no conservative streamfunction exists')
        # Keep both compensated components until after subtracting a single
        # global gauge at the shortest edge. Rounding a large global psi first
        # would lose tiny-edge increments that a later local shift cannot undo.
        # This conditioning choice does not alter the traversal/closure edge or
        # any flux; it changes all continuum potential values by one constant.
        prefixes = np.empty((len(increments), 2))
        total = 0.; correction = 0.
        for edge_index, value in enumerate(increments):
            _cancel(cancel); prefixes[edge_index] = total, correction
            updated = total+value
            correction += ((total-updated)+value if abs(total) >= abs(value) else (value-updated)+total)
            total = updated
        gauge_total, gauge_correction = prefixes[gauge_edge]
        for edge_index, (element, edge) in enumerate(self._boundary):
            _cancel(cancel); i, j = _EDGES[edge]
            xy = self.mesh.points[self.mesh.cells[element, [i, j]]]
            tangent = xy[1]-xy[0]; normal_length = np.array([tangent[1], -tangent[0]])
            trace = velocity[element, [i, edge+3, j]]@normal_length
            total, correction = prefixes[edge_index]
            terms = (total, correction, -gauge_total, -gauge_correction)
            full[self._cells[element, i]] = math.fsum(terms)
            for local, t in ((3+2*edge, 1/3), (4+2*edge, 2/3)):
                partial = math.fsum(map(float, trace*_partial_integrals(t)))
                full[self._cells[element, local]] = math.fsum((*terms, partial))
        return full, net, flux_scale, 'integrated-P2-normal-trace'

    def evaluate(self, element_node_velocity, *, boundary_streamfunction=None, cancel=None):
        if input_shape(element_node_velocity) != (len(self.mesh.cells), 6, 2):
            raise TectonicsError('local P2 velocity requires (elements,6,2) shape')
        with self._operation(cancel), self.budget.reserve(1800*len(self.mesh.cells)
                +64*len(self._points)+1024**2, category='subduction-transport-evaluate'):
            velocity = read_array(element_node_velocity, 'mechanical local P2 velocity')
            potential, net, flux_scale, mode = self._boundary_values(velocity, boundary_streamfunction, cancel)
            rhs = np.zeros(len(self._points)); elements = len(self.mesh.cells)
            for start in range(0, elements, _BATCH):
                _cancel(cancel); end = min(start+_BATCH, elements)
                gradient = _gradient(self._dq, self.mesh.grad_lambda[start:end])
                curl = gradient[..., ::-1].copy(); curl[..., 1] *= -1
                target = np.einsum('qn,end->eqd', self._p2, velocity[start:end], optimize=True)
                local = np.einsum('eqnd,eqd,q,e->en', curl, target, self._weights,
                                  self.mesh.area[start:end], optimize=True)
                rhs += np.bincount(self._cells[start:end].ravel(), weights=local.ravel(), minlength=len(rhs))
            reduced = rhs[self._free]-self._boundary_matrix@potential[self._fixed]
            factor = self._get_factor(cancel); linear_error = 0.
            if factor is not None:
                value = factor.solve(reduced)
                residual = self._matrix@value-reduced
                scale = np.abs(self._matrix)@np.abs(value)+np.abs(reduced)
                linear_error = float(np.max(np.abs(residual)/np.maximum(scale, np.finfo(float).tiny)))
                if not np.isfinite(value).all() or linear_error > 1e-10:
                    raise TectonicsError('scalar thermal-transfer residual failed')
                potential[self._free] = value
            output = np.empty_like(velocity); div_max = div_scaled = 0.; input_div_integral = 0.
            output_div_integral = change_integral = input_integral = 0.
            for start in range(0, elements, _BATCH):
                _cancel(cancel); end = min(start+_BATCH, elements)
                local_potential = potential[self._cells[start:end]]
                pg = _potential_gradient(self._dn, self.mesh.grad_lambda[start:end], local_potential)
                output[start:end, :, 0] = pg[:, :, 1]; output[start:end, :, 1] = -pg[:, :, 0]
                _, derivative, _ = basis(self._bary, self.mesh.grad_lambda[start:end], budget=self.budget, cancel=cancel)
                old_grad = np.einsum('end,eqnj->eqdj', velocity[start:end], derivative, optimize=True)
                new_grad = np.einsum('end,eqnj->eqdj', output[start:end], derivative, optimize=True)
                old_div = old_grad[:, :, 0, 0]+old_grad[:, :, 1, 1]
                new_div = new_grad[:, :, 0, 0]+new_grad[:, :, 1, 1]
                bound = np.einsum('end,eqnd->eq', np.abs(output[start:end]), np.abs(derivative), optimize=True)
                div_max = max(div_max, float(np.max(np.abs(new_div))))
                div_scaled = max(div_scaled, float(np.max(np.abs(new_div)/np.maximum(bound, np.finfo(float).tiny))))
                weights = self.mesh.area[start:end, None]*self._weights
                input_div_integral += float(np.sum(weights*old_div**2))
                output_div_integral += float(np.sum(weights*new_div**2))
                change = np.einsum('qn,end->eqd', self._p2, output[start:end]-velocity[start:end], optimize=True)
                target = np.einsum('qn,end->eqd', self._p2, velocity[start:end], optimize=True)
                change_integral += float(np.sum(weights*np.sum(change**2, axis=-1)))
                input_integral += float(np.sum(weights*np.sum(target**2, axis=-1)))
            boundary_error = 0.; output_flux = []
            for element, edge in self._boundary:
                i, j = _EDGES[edge]; xy = self.mesh.points[self.mesh.cells[element, [i, j]]]
                tangent = xy[1]-xy[0]; length = float(np.linalg.norm(tangent))
                normal = np.array([tangent[1], -tangent[0]])/length
                after = output[element, [i, edge+3, j]]@normal
                before = velocity[element, [i, edge+3, j]]@normal
                boundary_error = max(boundary_error, float(np.max(np.abs(after-before))))
                output_flux.append(length*math.fsum((float(after[0])/6, 2*float(after[1])/3, float(after[2])/6)))
            jump = 0.
            if len(self._interior):
                faces = self._interior; e0, e1 = faces[:, 0], faces[:, 4]
                left = output[e0[:, None], faces[:, 1:4]]; right = output[e1[:, None], faces[:, 5:8]]
                xy = self.mesh.points[self.mesh.cells[e0[:, None], faces[:, 1:3]]]
                tangent = xy[:, 1]-xy[:, 0]; normal = np.column_stack((tangent[:, 1], -tangent[:, 0]))
                normal /= np.linalg.norm(normal, axis=1)[:, None]
                jump = float(np.max(np.abs(np.einsum('end,ed->en', left-right, normal))))
            speed = max(float(np.max(np.abs(velocity))), float(np.max(np.abs(output))), np.finfo(float).tiny)
            if (not np.isfinite(output).all() or div_scaled > 1e-10 or jump > 1e-10*speed
                    or mode == 'integrated-P2-normal-trace' and boundary_error > 1e-10*speed):
                raise TectonicsError('published thermal velocity violates divergence or normal-trace gates: '
                    f'scaled divergence={div_scaled}, normal jump={jump}, boundary change={boundary_error}, speed={speed}')
            area = math.fsum(map(float, self.mesh.area))
            record = dict(method='C0-P3-streamfunction-L2-curl-fit', boundary_mode=mode,
                input_boundary_net_flux=net, input_boundary_absolute_flux_scale=flux_scale,
                output_boundary_net_flux=math.fsum(output_flux),
                boundary_normal_max_change=boundary_error, interior_normal_max_jump=jump,
                input_divergence_rms_per_km=math.sqrt(input_div_integral/area),
                divergence_rms_per_km=math.sqrt(output_div_integral/area),
                divergence_max_per_km=div_max, scaled_divergence_max=div_scaled,
                velocity_change_l2=math.sqrt(change_integral), input_velocity_l2=math.sqrt(input_integral),
                linear_residual=linear_error, factorisations=self._factorisations,
                tangential_velocity_preserved=False, mechanical_field_replaced=False,
                p3_nodes=len(self._points), free_scalar_nodes=len(self._free), elements=elements)
            payload = output.tobytes(), potential.tobytes(), _json(record)
            digest = hashlib.sha256(self.plan_id.encode()+mode.encode()+velocity.tobytes()+payload[0]+payload[1])
            _cancel(cancel)
            return ConservativeVelocityResult(self.plan_id, digest.hexdigest(), elements, *payload)

    def release_factor(self):
        self._check()
        if self._active: raise TectonicsError('cannot release an active thermal-transfer factor')
        self._factor = None
        if self._factor_lease is not None:
            self._factor_lease.__exit__(None, None, None); self._factor_lease = None

    def close(self):
        if self._closed: return
        self.release_factor(); self._matrix = self._boundary_matrix = None
        self._closed = True; self._lease.__exit__(None, None, None)

    def __enter__(self): self._check(); return self
    def __exit__(self, *_): self.close()
