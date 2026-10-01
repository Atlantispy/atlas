"""Source-bound finite-region 3D full-stress Stokes mechanics.

SPDX-License-Identifier: AGPL-3.0-only

Q2/Q1 hexahedra; SI at the public boundary, dimensionless linear algebra.
This is an actual regional mechanical solve, not a geological evolution loop.
Viscosity and an optional symmetric deviatoric extra stress are supplied by the
material producer. No fracture, thermal evolution, remap or pressure-dependent
constitutive law is inferred. Mixed velocity/traction conditions use outward
traction of sigma=2*eta*symgrad(u)+extra_stress-p*I.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from concurrent.futures import CancelledError
import hashlib
import inspect
import json
import math
from pathlib import Path
import threading
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres, spilu, splu

from . import regional_elements3d as elements3d
from . import regional_multigrid3d as multigrid3d
from . import regional_solver_selection3d as selection3d
from ._validation import TectonicsError, scalar, frozen
from .regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from .resources import select_budget, MemoryLimitError
from .reuse import ExecutionContext
from .stokes_execution import _native_lease, _factored_scale

SIDES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_EPS = float(np.finfo(float).eps)
_TINY = float(np.finfo(float).tiny)
_LINEAR_RTOL = 1e-11
# Every gate is relative to the magnitude of its own operands, so it is unchanged
# when caller-chosen RegionalMechanicsScales rescale the dimensionless problem.
# The only floor is representability: below this the GMRES target
# rtol*||rhs|| would no longer be a normal binary64 number.
_RHS_FLOOR = _TINY/(_EPS*_LINEAR_RTOL)


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise CancelledError('3D regional mechanics cancelled')


def _name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise TectonicsError(label+' must be a nonempty bounded identifier')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _array(value, shape, name, *, scalar_ok=False, positive=False):
    a = np.asarray(value)
    if a.dtype.kind not in 'fiu' or a.dtype.kind == 'b':
        raise TectonicsError(name+' requires real numeric data')
    if scalar_ok and a.ndim == 0:
        a = np.full(shape, float(a))
    if a.shape != shape or not np.all(np.isfinite(a)):
        raise TectonicsError(name+' has incorrect shape or nonfinite data')
    if positive and np.any(a <= 0):
        raise TectonicsError(name+' must be strictly positive')
    return frozen(np.asarray(a, dtype=float))


def _digest_array(a):
    return hashlib.sha256(a.tobytes()).hexdigest()


def _sparse_bytes(a):
    return a.data.nbytes+a.indices.nbytes+a.indptr.nbytes


def _magnitude(m):
    """|m| sharing the sparse structure; only the data array is new."""
    return sparse.csr_matrix((np.abs(m.data), m.indices, m.indptr), shape=m.shape)


def _assembly_bytes(nc, nv, np_):
    """Conservative sparse assembly, work arrays and result envelope of the assembled routes.

    Allocator overhead and caller buffers are not an operating-system RSS guarantee.
    """
    return 8*1024**2+420000*nc+3000*(3*nv+np_)


# SuperLU commits its L/U working arrays before factoring: two float64 value and
# two int32 index arrays of fill*nnz entries each, 24*fill bytes per input entry
# whatever the realised fill. The ILU fill is the fill_factor passed to spilu;
# the complete LU uses SuperLU's initial estimate (measured 720-724 bytes per
# entry of K after warm-up: fill 30). The per-unknown term covers permutation,
# supernode and work arrays; these remain accounting bounds, not process RSS.
_ILU_FILL, _LU_FILL = 8, 30


def _ilu_allowance(nnz, n):
    """Admitted bytes for the incomplete factor of the free velocity block (checked after)."""
    return 24*_ILU_FILL*nnz+1024*n


def _lu_allowance(nnz, n):
    """Complete factor's initial working storage or dense fill bound, plus O(n) work."""
    return max(24*_LU_FILL*nnz, 16*n*n)+1024*n


def _local_tokens(module):
    """Track the new modules as well as the retained context's fixed inventory."""
    out = []
    for name, value in sorted(vars(module).items()):
        candidates = [(name, value)]
        if inspect.isclass(value) and value.__module__ == module.__name__:
            candidates += [(name+'.'+k, v.__func__ if isinstance(v, (staticmethod, classmethod)) else v)
                           for k, v in sorted(vars(value).items())]
        for key, fn in candidates:
            if inspect.isfunction(fn) and fn.__module__ == module.__name__:
                out.append((key, fn, fn.__code__, repr(fn.__defaults__), repr(fn.__kwdefaults__)))
    return tuple(out)


def _selection(cells, lengths, scales, pattern, viscosity_pa_s, available):
    """The ``auto`` selection record for a validated box, pattern and scales.

    Both methods' complete reservations are predicted with their own formulas
    (``_assembly_bytes``/``_ilu_allowance`` and the multigrid projections),
    without assembling, factoring or solving anything.
    """
    nc = int(np.prod(cells))
    nv = int(np.prod(2*np.asarray(cells)+1))
    np_ = int(np.prod(np.asarray(cells)+1))
    eta = _array(viscosity_pa_s, (nc, 27), 'quadrature viscosity', scalar_ok=True, positive=True)
    dimension = _factored_scale(np.asarray(lengths), (), (scales.length_m,), 'scaled box')
    features = selection3d.workload_features(cells, np.asarray(lengths)/np.asarray(cells), eta, pattern)
    nnz, free = selection3d.assembled_free_nonzeros(cells, pattern)
    needs = dict(gmres=_assembly_bytes(nc, nv, np_)+_ilu_allowance(nnz, free),
                 multigrid=selection3d.multigrid_bytes(cells, np.asarray(dimension, dtype=float)/np.asarray(cells),
                                                       pattern))
    try:
        return selection3d.select(features, needs, available)
    except ValueError as exc:
        raise TectonicsError(str(exc)) from exc


class _SharedPreparation:
    """Viscosity-independent preparation a changed-viscosity plan may reuse.

    Holds only geometry-bound data (mesh tables, the divergence matrix and, for
    the multigrid candidate, masks, patterns and transfers). Its key is checked
    against the new plan's cells, scaled dimensions, boundary pattern and method.
    """
    __slots__ = ('key', 'mesh', 'B', 'geometry')

    def __init__(self, key, mesh, B, geometry):
        self.key, self.mesh, self.B, self.geometry = key, mesh, B, geometry


class PreparedRegionalStokes3D:
    """Prepared heterogeneous finite-box solver with bounded reusable factors.

    ``boundary_types`` explicitly maps each side to three velocity/traction
    strings, in x,y,z order. Velocity input is one shared nodal array, so corners
    cannot acquire conflicting copies. Traction input uses face Gauss samples.
    Only the latest immutable solution is cached. Caller-held results are caller
    storage, not retained by an unbounded history. A changed material needs a new
    plan; ``with_viscosity`` prepares one that reuses only viscosity-independent
    structure. ``auto`` (the default) chooses ``multigrid`` or ``gmres`` for this
    workload before anything is reserved (see ``regional_solver_selection3d``)
    and records the request, the resolved method and the reason in the plan
    definition. ``gmres`` (assembled operator, incomplete factor) is the reference
    path; ``direct`` is an explicitly bounded check. ``multigrid`` is the
    matrix-free method (see ``regional_multigrid3d``): the same equations, gates
    and outputs without an assembled velocity block. Explicit methods are
    honoured unchanged.
    """
    def __init__(self, cells, lengths_m, viscosity_pa_s, boundary_types, *,
                 scales, reference_viscosity_pa_s, frame_id, vertical_datum,
                 material_source, physical_mean_pressure_pa=None, method='auto',
                 budget=None, cancel=None, _shared=None, _selection_available_bytes=None):
        start = perf_counter()
        if (type(cells) not in (tuple, list) or len(cells) != 3
                or any(type(n) is not int or not 2 <= n <= 24 for n in cells)):
            raise TectonicsError('3D grid needs three integer cell counts from 2 to 24')
        if type(scales) is not RegionalMechanicsScales:
            raise TectonicsError('explicit RegionalMechanicsScales required')
        if len(lengths_m) != 3:
            raise TectonicsError('three physical lengths required')
        lengths = tuple(scalar(x, 'length', positive=True) for x in lengths_m)
        eta0 = scalar(reference_viscosity_pa_s, 'reference viscosity', positive=True)
        for value, name in ((frame_id, 'frame'), (vertical_datum, 'vertical datum'),
                            (material_source, 'material source')):
            _name(value, name)
        if method not in ('auto', 'gmres', 'direct', 'multigrid'):
            raise TectonicsError('select auto, gmres, explicit direct or multigrid method')
        if _selection_available_bytes is not None and (
                method != 'auto' or type(_selection_available_bytes) is not int
                or _selection_available_bytes < 0):
            raise TectonicsError('a pinned selection allowance requires auto and nonnegative integer bytes')
        if type(boundary_types) is not dict or set(boundary_types) != set(SIDES):
            raise TectonicsError('all six boundary sides must be declared')
        pattern = {}
        for side in SIDES:
            kinds = boundary_types[side]
            if len(kinds) != 3 or any(k not in ('velocity', 'traction') for k in kinds):
                raise TectonicsError('each side needs three velocity/traction conditions')
            pattern[side] = tuple(kinds)
        self._closed = False
        self._active = False
        self._owner = threading.get_ident()
        self._context = self._latest = self._latest_key = self._mode_cache = None
        self._mg = self._shared = None
        self._reservations = []
        self._resource = select_budget(budget)
        self._scales, self._eta0 = scales, eta0
        self._cells, self._lengths, self._pattern = tuple(cells), lengths, pattern
        self._identity = dict(frame_id=frame_id, vertical_datum=vertical_datum,
                              physical_mean_pressure_pa=physical_mean_pressure_pa)
        if type(_shared) is list:
            # Handed over by with_viscosity: take the only reference, so structure
            # this plan does not reuse is freed rather than held unreserved.
            _shared = _shared.pop() if _shared else None
        self._requested_method, self._selection = method, None
        self._selection_available_bytes = _selection_available_bytes
        if method == 'auto':
            # Decided before anything is reserved; nothing is solved or timed to decide.
            clock = perf_counter()
            self._selection, available = self._select(viscosity_pa_s)
            method = self._selection['method']
            clock = perf_counter()-clock
            if type(_shared) is _SharedPreparation and _shared.key[-1] != method:
                _shared = None                  # prepared for the other method: nothing is shared
        self._method = method
        self._reused = _shared is not None
        self._stats = dict(solves=0, result_hits=0, coupling_response_hits=0,
                           factorizations=0, krylov_iterations=0)
        if method == 'multigrid':
            self._stats.update(preconditioner_applications=0, geometry_reused=_shared is not None)
        if self._selection is not None:
            self._stats['solver_selection'] = dict(requested='auto', method=method,
                reason=self._selection['reason'], seconds=clock, available_bytes=available,
                selection_available_bytes=(available if self._selection_available_bytes is None
                                           else self._selection_available_bytes))
        nc = int(np.prod(cells))
        nv = int(np.prod(2*np.asarray(cells)+1))
        np_ = int(np.prod(np.asarray(cells)+1))
        if method != 'multigrid':
            self._retain(_assembly_bytes(nc, nv, np_), 'regional3d-assembly')
        try:
            if method == 'multigrid':
                # Geometry tables, operators, Krylov/level work and the result
                # envelope; factors are admitted separately once their sizes are
                # known. Inside the try, so a refusal returns every reservation.
                projected = multigrid3d.projected_bytes(cells)
                self._retain(projected['structure'], 'regional3d-multigrid')
                self._retain(projected['work'], 'regional3d-multigrid-work')
            _cancel(cancel)
            import sys
            self._modules = (sys.modules[__name__], elements3d, multigrid3d, selection3d)
            for module in self._modules:
                if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != module._LOADED_SOURCE_SHA256:
                    raise TectonicsError('3D source changed since import; restart the process')
            self._tokens = tuple(_local_tokens(m) for m in self._modules)
            self._context = ExecutionContext('scipy')
            self._context_id = self._context.identity
            dimension = _factored_scale(np.asarray(lengths), (), (scales.length_m,), 'scaled box')
            key = (tuple(cells), tuple(float(x) for x in dimension),
                   tuple((side, pattern[side]) for side in SIDES), method)
            if _shared is not None and (type(_shared) is not _SharedPreparation or _shared.key != key):
                raise TectonicsError('reused 3D preparation does not match this geometry, boundary or method')
            self._mesh = elements3d.TaylorHoodBox(tuple(cells), tuple(dimension)) if _shared is None else _shared.mesh
            mesh = self._mesh
            self._eta = _array(viscosity_pa_s, (nc, 27), 'quadrature viscosity', scalar_ok=True, positive=True)
            eta = _factored_scale(self._eta, (), (eta0,), 'scaled viscosity')
            if method == 'multigrid':
                # No assembled velocity block: the divergence matrix is geometric.
                self._A = self._pd = None
                self._B = (sparse.csr_matrix((mesh._b_data, mesh._b_indices, mesh._b_ptr),
                           shape=(mesh.np, 3*mesh.nv)) if _shared is None else _shared.B)
                self._pw = np.array(mesh._pressure_weights)
            else:
                with _native_lease():
                    self._A, self._B, self._pw, self._pd = mesh.assemble(eta, cancel=cancel)
            coord = mesh.velocity_coordinates
            mask = np.zeros((mesh.nv, 3), dtype=bool)
            for side in SIDES:
                axis = 'xyz'.index(side[0])
                # The generated endpoint may differ from the requested length
                # by one rounding unit. Select the actual endpoint layer.
                on = coord[:, axis] == (0. if side[1] == '0' else np.max(coord[:, axis]))
                for component, kind in enumerate(pattern[side]):
                    if kind == 'velocity':
                        mask[on, component] = True
            self._mask = mask
            self._fixed = np.flatnonzero(mask.ravel())
            self._free = np.flatnonzero(~mask.ravel())
            # A constrained rigid-motion basis must have full rank; do not add
            # hidden pins that can change geological tractions.
            xyz = (coord-np.asarray(dimension)/2)/max(dimension)
            rigid = np.zeros((mesh.nv, 3, 6))
            for j in range(3):
                rigid[:, j, j] = 1.
                rigid[:, :, 3+j] = np.cross(np.eye(3)[j], xyz)
            if np.linalg.matrix_rank(rigid.reshape(-1, 6)[self._fixed]) != 6:
                raise TectonicsError('boundary conditions leave a free rigid translation or rotation')
            if method == 'multigrid':
                # B_f^T 1 is (B^T 1) on the free columns; no second copy of B.
                self._Af = self._Bf = None
                pressure_leak = np.asarray(self._B.T@np.ones(mesh.np)).ravel()[self._free]
            else:
                self._Af = self._A[self._free][:, self._free].tocsc()
                self._Bf = self._B[:, self._free].tocsr()
                pressure_leak = np.asarray(self._Bf.T@np.ones(mesh.np)).ravel()
            # Relative to the divergence entries themselves (they scale as the
            # squared dimensionless spacing); an absolute floor would mistake a
            # small traction box for a closed one.
            self._gauge = bool(np.linalg.norm(pressure_leak, np.inf) < 1e-12*np.max(np.abs(self._B.data)))
            self._faces = {side: mesh._face(side)[:3] for side in SIDES}
            if physical_mean_pressure_pa is not None:
                physical_mean_pressure_pa = scalar(physical_mean_pressure_pa, 'physical mean pressure')
                if not self._gauge:
                    raise TectonicsError('normal traction already fixes pressure; a second datum is forbidden')
            self._physical = not self._gauge or physical_mean_pressure_pa is not None
            self._mean = physical_mean_pressure_pa
            self._w = self._pw/np.sum(self._pw)
            if method == 'multigrid':
                self._prepare_multigrid(eta, pattern, projected, _shared, cancel)
            else:
                if self._gauge:
                    w = sparse.csc_matrix(self._w[:, None])
                    self._K = sparse.bmat([[self._Af, self._Bf.T, None],
                                          [self._Bf, None, w], [None, w.T, None]], format='csc')
                else:
                    self._K = sparse.bmat([[self._Af, self._Bf.T], [self._Bf, None]], format='csc')
                if method == 'direct':
                    allowance = _lu_allowance(self._K.nnz, self._K.shape[0])
                else:
                    allowance = _ilu_allowance(self._Af.nnz, self._Af.shape[0])
                self._retain(allowance, 'regional3d-factor')
                with _native_lease():
                    _cancel(cancel)
                    self._factor = (splu(self._K, permc_spec='COLAMD') if method == 'direct'
                                    else spilu(self._Af, drop_tol=1e-4, fill_factor=float(_ILU_FILL),
                                               permc_spec='COLAMD'))
                # Reading L/U builds CSC copies retained by SciPy. Use SuperLU's
                # stored-entry count for the same realised-factor check instead.
                if 12*self._factor.nnz+8*(self._factor.shape[0]+1) > allowance:
                    raise MemoryLimitError('realised factor exceeded admitted factor allowance')
                self._P = LinearOperator(self._K.shape, matvec=self._precondition, dtype=float) if method == 'gmres' else None
            self._stats['factorizations'] = 1
            self._shared = _SharedPreparation(key, mesh, self._B if method == 'multigrid' else None,
                                              self._mg.geometry if method == 'multigrid' else None)
            self._definition = dict(schema='atlas.regional3d-plan.v1', cells=list(cells),
                lengths_m=list(lengths), scales=asdict(scales), reference_viscosity_pa_s=eta0,
                viscosity_sha256=_digest_array(self._eta), boundary_types=pattern,
                frame_id=frame_id, vertical_datum=vertical_datum, material_source=material_source,
                physical_mean_pressure_pa=physical_mean_pressure_pa, method=method,
                linear_rtol=_LINEAR_RTOL, pressure_gauge_required=self._gauge,
                acceptance_scaling='relative to own operands; no absolute floor except representability',
                element='Q2/Q1 tensor-product hexahedron; 3-point Gauss in each direction',
                coordinates='Cartesian right-handed x,y horizontal; z up from box bottom',
                execution=self._context_id)
            if self._selection is not None:
                self._definition.update(requested_method='auto', solver_selection=self._selection)
            if method == 'multigrid':
                self._definition['solver'] = dict(multigrid3d.SETTINGS, max_iterations=1200,
                                                  levels=self._mg.levels())
            self.plan_id = _hash(self._definition)
            self._verify()
            self._stats['prepare_seconds'] = perf_counter()-start
        except BaseException:
            self.close()
            raise

    def _prepare_multigrid(self, eta, pattern, projected, shared, cancel):
        """Matrix-free operator, hierarchy and factors for the candidate method."""
        mesh = self._mesh
        with _native_lease():
            _cancel(cancel)
            geometry = (multigrid3d.StructuredGeometry(mesh, pattern, self._fixed, self._free, self._B, cancel)
                        if shared is None else shared.geometry)
            allowance = multigrid3d.factor_allowance(geometry)
            self._retain(allowance, 'regional3d-multigrid-factor')
            try:
                self._mg = multigrid3d.MultigridStokes(geometry, eta, cancel=cancel)
            except ValueError as exc:
                raise TectonicsError('3D multigrid preparation refused: '+str(exc)) from exc
        if self._mg.factor_bytes() > allowance:
            raise MemoryLimitError('realised multigrid factors exceeded admitted factor allowance')
        structure = self._mg.structure_bytes()+sum(a.nbytes for a in (
            mesh.velocity_coordinates, mesh.velocity_cells, mesh.pressure_cells,
            mesh.quadrature_coordinates, self._eta, self._fixed, self._free))
        if structure > projected['structure']:
            raise MemoryLimitError('realised multigrid structure exceeded admitted allowance')
        self._K = self._factor = self._P = None

    def _select(self, viscosity_pa_s):
        """Resolve ``auto`` before any reservation; refuse when neither method fits."""
        available = self._resource.available_bytes
        # Evolution pins the admission choices for restart reproducibility. This
        # is a decision allowance only: every actual reservation still charges
        # the live shared budget and may refuse, never silently choose a fallback.
        decision_available = (available if self._selection_available_bytes is None
                              else self._selection_available_bytes)
        record = _selection(self._cells, self._lengths, self._scales, self._pattern,
                            viscosity_pa_s, decision_available)
        if record['method'] is None:
            needs = record['admission']
            raise MemoryLimitError('automatic 3D solver selection refused: neither gmres (%d bytes) nor '
                                   'multigrid (%d bytes) fits the %d bytes available; no limit was raised'
                                   % (needs['gmres']['bytes'], needs['multigrid']['bytes'], decision_available))
        return record, available

    def with_viscosity(self, viscosity_pa_s, *, material_source, cancel=None, release=False):
        """Prepare a new plan for changed viscosity, reusing geometry-bound structure.

        Cells, lengths, boundary pattern, scales, reference viscosity, frame,
        datum, mean pressure, requested method and budget are carried over. Only viscosity-independent data are shared
        (mesh tables, divergence matrix, masks, sparsity patterns and multigrid
        transfers); operators, factors, caches and identity are new. With
        ``release`` this plan is closed first, so its operators and reservations
        are returned before the new plan is admitted (the same peak as closing and
        preparing afresh); otherwise it remains open and unchanged.

        An ``auto`` plan selects again for the new viscosity exactly as a fresh
        plan with the same selection allowance would. If that changes the method, nothing is shared and the plan
        is prepared afresh; the old structure is released with the old plan.
        """
        self._verify()
        arguments = dict(scales=self._scales, reference_viscosity_pa_s=self._eta0, material_source=material_source,
                         method=self._requested_method, budget=self._resource, cancel=cancel,
                         _selection_available_bytes=self._selection_available_bytes,
                         _shared=[self._shared], **self._identity)
        cells, lengths, pattern = list(self._cells), self._lengths, dict(self._pattern)
        if release:
            self.close()
        return PreparedRegionalStokes3D(cells, lengths, viscosity_pa_s, pattern, **arguments)

    def _retain(self, count, category):
        guard = self._resource.reserve(int(count), category=category)
        guard.__enter__()
        self._reservations.append(guard)

    def _verify(self):
        if self._closed:
            raise TectonicsError('3D plan is closed')
        if tuple(_local_tokens(m) for m in self._modules) != self._tokens:
            raise TectonicsError('loaded 3D implementation changed')
        self._context.verify()

    @contextmanager
    def _operation(self, cancel):
        if threading.get_ident() != self._owner or self._active:
            raise TectonicsError('prepared 3D plan is single-owner and non-reentrant')
        self._verify()
        _cancel(cancel)
        self._active = True
        try:
            with _native_lease():
                yield
            _cancel(cancel)
            self._verify()
        finally:
            self._active = False

    def coordinates(self, site='quadrature'):
        with self._operation(None):
            if site in SIDES:
                points = self._mesh.boundary_quadrature(site)
            elif site == 'quadrature':
                points = self._mesh.quadrature_coordinates
            elif site == 'velocity':
                points = self._mesh.velocity_coordinates
            elif site == 'pressure':
                points = self._mesh.pressure_coordinates
            else:
                raise TectonicsError('unknown 3D sampling location')
            return frozen(_factored_scale(points, (self._scales.length_m,), (), 'coordinates'))

    def velocity_mask(self):
        self._verify()
        return self._mask.copy()

    def descriptor(self):
        self._verify()
        return json.loads(_json(self._definition))

    @property
    def method(self):
        """The method that prepared this plan (``auto`` already resolved)."""
        return self._method

    @property
    def requested_method(self):
        return self._requested_method

    def solver_selection(self):
        """A copy of the automatic selection record; None for an explicit method."""
        return None if self._selection is None else json.loads(_json(self._selection))

    def statistics(self):
        if self._mg is not None:
            self._stats['preconditioner_applications'] = self._mg.applications
        return dict(self._stats, budget=self._resource.statistics())

    def _precondition(self, rhs):
        nf, np_ = len(self._free), self._mesh.np
        zv = self._factor.solve(rhs[:nf])
        rp = rhs[nf:nf+np_]-self._Bf@zv
        if self._gauge:
            wdiv = self._w/self._pd
            lam = (rhs[-1]+wdiv@rp)/(wdiv@self._w)
            zp = (self._w*lam-rp)/self._pd
        else:
            lam = None
            zp = -rp/self._pd
        zv -= self._factor.solve(self._Bf.T@zp)
        return np.r_[zv, zp, lam] if self._gauge else np.r_[zv, zp]

    def _absolute_boundary_flux(self, lift):
        """Integrated |u.n| over all six faces (exact 3x3 Gauss for Q2 traces)."""
        nodal = lift.reshape(-1, 3)
        total = []
        for side in SIDES:
            cells, shape, weights = self._faces[side]
            normal = nodal[self._mesh.velocity_cells[cells], 'xyz'.index(side[0])]
            total.append(float(np.sum(np.abs(normal@shape.T)*weights)))
        return math.fsum(total)

    def _net_flux_free(self, field):
        """Zero net boundary flux of a nodal field, at any scale.

        Relative to the boundary flux actually supplied, not to max(1, |d|): a
        closed incompressible box admits no net inflow at any magnitude. The
        second term bounds the rounding of the computed sum itself.
        """
        flux = float(np.sum(self._B@field))
        rounding = float(np.sum(abs(self._B)@np.abs(field)))
        return abs(flux) <= 2e-11*self._absolute_boundary_flux(field)+512*_EPS*rounding

    def net_flux_neutral(self, field_m):
        """Whether a nodal velocity/displacement field has zero net boundary flux.

        With a pressure gauge, a constant pressure c adds -c*(net flux of m) to
        the reaction projected on a mode m, so only projections on neutral modes
        (1^T B m = 0) are independent of the undetermined constant. Same test and
        tolerance as the closed-box compatibility gate.
        """
        self._verify()
        field = _array(field_m, (self._mesh.nv, 3), 'boundary field')
        return self._net_flux_free(field.ravel())

    def _linear(self, load, prescribed, mean, cancel, requested=False):
        d = prescribed.ravel()[self._fixed]
        lift = np.zeros(3*self._mesh.nv)
        lift[self._fixed] = d
        if self._gauge and not self._net_flux_free(lift):
            raise TectonicsError('incompressible closed-boundary velocity has nonzero net flux')
        if requested and not (np.any(load) or np.any(lift)):
            raise TectonicsError('nonzero 3D forcing underflows to zero in assembly; '
                                 'choose RegionalMechanicsScales near the problem magnitudes')
        multigrid = self._method == 'multigrid'
        lifted = self._mg.apply(lift) if multigrid else self._A@lift
        rv = (load-lifted)[self._free]
        rp = -self._B@lift
        # A declared mean pressure is added after solving: a closed box has
        # B_f^T 1 = 0, so it cannot change velocity, while inside the right-hand
        # side it would dominate every relative target and hide velocity error.
        rhs = np.r_[rv, rp, 0.] if self._gauge else np.r_[rv, rp]
        rhs_norm = float(np.linalg.norm(rhs, np.inf))
        forced = bool(np.any(load[self._free]) or np.any(lifted[self._free]) or np.any(rp))
        if forced and not rhs_norm >= _RHS_FLOOR:
            raise TectonicsError('3D load is zero or below binary64 relative precision after scaling; '
                                 'choose RegionalMechanicsScales near the problem magnitudes')
        _cancel(cancel)
        count = 0
        nf, npr = len(self._free), self._mesh.np
        if multigrid:
            # Assembled |A| row sums and products are regenerated from element
            # contributions (summed before the absolute value), not stored.
            magnitude_a, magnitude_b = None, _magnitude(self._B)
            stiffness = float(np.max(self._mg.row_magnitudes()[self._free], initial=0.))
        else:
            magnitude_a, magnitude_b = _magnitude(self._A), _magnitude(self._B)
            stiffness = float(np.max((magnitude_a@np.ones(3*self._mesh.nv))[self._free], initial=0.))
        latest = {}

        def products(u):
            """A u and |A||u| with the assembled entries of A."""
            if multigrid:
                return self._mg.products(u, cancel=cancel)
            return self._A@u, magnitude_a@np.abs(u)

        def implied_velocity(x):
            """Momentum operand scale and the velocity magnitude it implies."""
            if 'x' in latest and np.array_equal(latest['x'], x):
                return latest['value']
            u = lift.copy(); u[self._free] = x[:nf]
            au, viscous = products(u)
            scale = float(np.max((viscous+magnitude_b.T@np.abs(x[nf:nf+npr])
                                  +np.abs(load))[self._free], initial=0.))
            latest['x'] = x.copy()
            latest['value'] = (u, scale, (scale/stiffness if stiffness > 0. else 0.), au, viscous)
            return latest['value']

        def solve(vector, candidate=False):
            """Solve K y = vector. A refinement correction (candidate=True) that
            GMRES does not converge is still returned, flagged, for the gates to
            judge; a first solve that does not converge is refused."""
            nonlocal count
            size = float(np.linalg.norm(vector, np.inf))
            if size == 0.:
                return (np.zeros_like(vector), True) if candidate else np.zeros_like(vector)
            # Unit right-hand side: SciPy's internal 2-norms can neither underflow
            # nor overflow, so the representable range is the whole gate range.
            if self._method == 'direct':
                y = self._factor.solve(vector/size)*size
                return (y, True) if candidate else y
            def callback(_):
                nonlocal count
                count += 1
                _cancel(cancel)
            if multigrid:
                # Aims for a stricter target but counts as converged only when the
                # recomputed true residual meets the reference's own relative target
                # (never looser), with the same 1200-iteration ceiling. The method is
                # flexible, so no variation of the preconditioner could invalidate
                # its Krylov relation.
                try:
                    y, converged, _ = self._mg.solve(vector/size, self._gauge,
                        min(_LINEAR_RTOL, multigrid3d.SETTINGS['krylov_rtol']), 1200, callback,
                        accept=_LINEAR_RTOL)
                except (FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
                    raise TectonicsError('3D multigrid Krylov solve failed: '+str(exc)) from exc
                if candidate:
                    return y*size, converged
                if not converged:
                    raise TectonicsError('3D FGMRES-DR did not converge; no silent direct fallback')
                return y*size
            # atol=0: SciPy then stops at rtol*||rhs||_2, a purely relative target.
            y, info = gmres(self._K, vector/size, M=self._P, rtol=_LINEAR_RTOL, atol=0.,
                            restart=60, maxiter=1200, callback=callback, callback_type='legacy')
            if candidate:
                return y*size, info == 0
            if info != 0:
                raise TectonicsError('3D GMRES did not converge; no silent direct fallback')
            return y*size

        def gauged(x):
            # Enforce the zero-mean gauge exactly after every solve (w^T 1 = 1 and
            # B_f^T 1 = 0, so velocity is unaffected): no gate checks the constant
            # in pressure units, and it must not inflate the operand scales.
            if self._gauge:
                x[nf:nf+npr] -= float(self._w@x[nf:nf+npr])
            return x

        def block(r, scale):
            # Componentwise (Oettli-Prager) backward error, row by row, so a weak
            # region's rows are not judged against a strong region's magnitudes;
            # rows below 1e-8 of the largest magnitude are judged at that floor.
            top = float(np.max(scale, initial=0.))
            if top == 0.:
                return 0. if not np.any(r) else math.inf
            return float(np.max(np.abs(r)/np.maximum(scale, 1e-8*top)))

        def assess(x):
            """Combined and blockwise residuals of a zero-mean solution."""
            if not np.all(np.isfinite(x)):
                raise TectonicsError('nonfinite 3D solve')
            if not multigrid:
                error = float(np.linalg.norm(self._K@x-rhs, np.inf)/rhs_norm) if forced else 0.
            u, _, implied, au, viscous = implied_velocity(x)
            p = x[nf:nf+npr]
            balance = au+self._B.T@p-load
            momentum_error = continuity_error = 0.
            residual = None
            if forced:
                # Blockwise backward errors against the magnitudes each block sums,
                # so a dominant continuity (or momentum) right-hand side cannot hide
                # an unbalanced other block inside the combined relative residual.
                ua = np.abs(u)
                # Momentum against the viscous operand |A||u| plus only the
                # round-off (256 eps) of the pressure and load terms: in a
                # load-dominated state those terms cancel, and at full weight they
                # would admit velocity errors far above 2e-9 of the velocity scale.
                balanced = magnitude_b.T@np.abs(p)+np.abs(load)
                momentum_error = block(balance[self._free], (viscous+(256*_EPS/2e-9)*balanced)[self._free])
                # Continuity against |B||u| plus the round-off (64 eps) of the
                # velocity magnitude the momentum block implies (momentum scale /
                # largest free-row sum of |A|): when pressure balances the load, u is round-off and
                # |B||u| alone is no scale, but a larger share would let an inflated
                # pressure-balanced scale hide continuity error.
                continuity = self._B@u
                continuity_terms = magnitude_b@(ua+(64*_EPS/2e-9)*implied)
                if self._gauge:
                    continuity = continuity+self._w*x[-1]
                    continuity_terms = continuity_terms+self._w*abs(x[-1])
                continuity_error = block(continuity, continuity_terms)
                if multigrid:
                    # K x - rhs from the same assembled-entry rows the blocks judge.
                    residual = np.concatenate((balance[self._free], continuity)
                                              + (([float(self._w@p)],) if self._gauge else ()))
            if multigrid:
                error = float(np.linalg.norm(residual, np.inf)/rhs_norm) if forced else 0.
            return dict(error=error, momentum=momentum_error, continuity=continuity_error,
                        u=u, p=p, balance=balance, magnitude=viscous, residual=residual)

        passes = lambda a: a['error'] <= 2e-9 and a['momentum'] <= 2e-9 and a['continuity'] <= 2e-9
        badness = lambda a: max(a['error'], a['momentum'], a['continuity'])

        def refine(x, state):
            """One refinement step, or None. A converged correction is kept; an
            unconverged GMRES correction is kept only if it lowers the worst gate
            ratio. Either way the published solution faces every gate."""
            try:
                correction, converged = solve(-state['residual'] if multigrid else rhs-self._K@x,
                                              candidate=True)
            except TectonicsError:
                return None
            trial = gauged(x+correction)
            if not np.all(np.isfinite(trial)):
                return None
            trial_state = assess(trial)
            if not converged and not badness(trial_state) < badness(state):
                return None
            return trial, trial_state

        refinements = 0
        if not forced:
            # Exactly unforced: the exact solution is zero, whatever the method.
            x = np.zeros_like(rhs)
        else:
            x = gauged(solve(rhs))
            # Load-dominated states (e.g. full rho*g balanced by pressure): the
            # velocity is a small part of a large solution, so a relative stop on
            # the whole right-hand side leaves it inaccurate while every backward
            # error is tiny. Refine (at most twice) only when the velocity is
            # below 1% of the magnitude the load implies.
            for _ in range(2):
                u_now, _, implied_now, _, _ = implied_velocity(x)
                if not (np.all(np.isfinite(x)) and float(np.max(np.abs(u_now))) < 1e-2*implied_now):
                    break
                step = refine(x, assess(x))
                _cancel(cancel)
                if step is None:
                    break
                x = step[0]
                refinements += 1
        _cancel(cancel)
        # Every gate and the work identity use the zero-mean solution; a declared
        # datum (which cannot change velocity) is added only for publication, so a
        # large datum cannot loosen any operand scale.
        state = assess(x)
        for _ in range(2):
            # Up to two working-precision refinement steps before refusing: they
            # restore componentwise backward stability to an otherwise accurate
            # solution of a badly scaled system (fixed-precision refinement). The
            # gates are unchanged.
            if not forced or passes(state):
                break
            step = refine(x, state)
            _cancel(cancel)
            if step is None:
                break
            x, state = step
            refinements += 1
        error, momentum_error, continuity_error = state['error'], state['momentum'], state['continuity']
        u, p, balance = state['u'], state['p'], state['balance']
        if not error <= 2e-9:
            raise TectonicsError('3D linear residual exceeds fixed acceptance tolerance')
        if not (momentum_error <= 2e-9 and continuity_error <= 2e-9):
            raise TectonicsError('3D momentum or continuity block residual exceeds fixed acceptance tolerance')
        # Free equations carry numerical residual, not externally applied force.
        constrained_reaction = np.zeros_like(balance)
        constrained_reaction[self._fixed] = balance[self._fixed]
        momentum_residual = np.zeros_like(balance)
        momentum_residual[self._free] = balance[self._free]
        datum_reaction = np.zeros_like(balance)
        if mean:
            datum_reaction[self._fixed] = mean*(self._B.T@np.ones(npr))[self._fixed]
        self._stats['krylov_iterations'] += count
        errors = dict(linear=error, momentum=momentum_error, continuity=continuity_error, forced=forced,
                      refinements=refinements)
        # |A||u| of the published solution, reused by the work round-off bound.
        datum = dict(mean=mean, reaction=datum_reaction.reshape(-1, 3), viscous_magnitude=state['magnitude'])
        return u.reshape(-1, 3), p, constrained_reaction.reshape(-1, 3), errors, count, momentum_residual, datum

    def solve(self, body_force_n_m3, velocity_m_s, traction_pa, *, parent_state_id,
              epoch_id, time_s, force_source, boundary_source, extra_stress_pa=None,
              stress_source='explicit-zero-extra-stress', cancel=None):
        """Solve the supplied same-time state. Histories are not advanced or reset.

        An extra-stress tensor can carry a constitutive producer's retained
        stress contribution. This interface does not itself integrate elasticity.
        Tractions are prescribed only on components marked traction; other
        supplied components must be zero. All side keys are required.
        """
        with self._operation(cancel):
            metadata, force, velocity, tractions, stress = self._request(
                body_force_n_m3, velocity_m_s, traction_pa, parent_state_id,
                epoch_id, time_s, force_source, boundary_source, extra_stress_pa, stress_source)
            key = _hash(dict(plan=self.plan_id, metadata=metadata,
                force=_digest_array(force), velocity=_digest_array(velocity), stress=_digest_array(stress),
                tractions={s:_digest_array(a) for s,a in tractions.items()}))
            if key == self._latest_key:
                self._stats['result_hits'] += 1
                return self._latest
            start = perf_counter()
            f, d, t, s, body, natural, load = self._scaled_request(force, velocity, tractions, stress)
            mean = 0. if self._mean is None else float(_factored_scale(np.asarray(self._mean),
                (self._scales.length_m,), (self._eta0, self._scales.velocity_m_s), 'pressure datum'))
            u,p,r,error,count,momentum,datum = self._linear(load,d,mean,cancel,self._requested(f,d,t,s))
            result = self._result(u,p,r,s,body,natural,load,momentum,metadata,error,count,datum)
            _cancel(cancel)
            self._verify()
            self._latest, self._latest_key = result, key
            self._stats['solves'] += 1
            self._stats['last_solve_seconds'] = perf_counter()-start
            return result

    def _request(self, force, velocity, tractions, parent, epoch, time, force_source,
                 boundary_source, stress, stress_source):
        for value,label in ((parent,'parent state'),(epoch,'epoch'),(force_source,'force source'),
                            (boundary_source,'boundary source'),(stress_source,'stress source')):
            _name(value,label)
        time = scalar(time, 'time')
        mesh = self._mesh
        force = _array(force,(mesh.nc,27,3),'body force',scalar_ok=True)
        velocity = _array(velocity,(mesh.nv,3),'boundary velocity',scalar_ok=True)
        stress = _array(0. if stress is None else stress,(mesh.nc,27,3,3),'extra stress',scalar_ok=True)
        magnitude = max(1.,float(np.max(np.abs(stress))))
        if (np.max(np.abs(stress-stress.swapaxes(-1,-2))) > 1e-12*magnitude
                or np.max(np.abs(np.trace(stress,axis1=-2,axis2=-1))) > 1e-12*magnitude):
            raise TectonicsError('extra stress must be symmetric and deviatoric')
        if type(tractions) is not dict or set(tractions) != set(SIDES):
            raise TectonicsError('all six traction sample fields are required; use explicit zeros')
        fields = {}
        for side in SIDES:
            a = _array(tractions[side],self._mesh.boundary_quadrature(side).shape,
                       'traction '+side,scalar_ok=True)
            for c,kind in enumerate(self._pattern[side]):
                if kind == 'velocity' and np.any(a[...,c] != 0):
                    raise TectonicsError('traction supplied on a prescribed velocity component')
            fields[side] = a
        return dict(parent_state_id=parent,epoch_id=epoch,time_s=time,force_source=force_source,
                    boundary_source=boundary_source,stress_source=stress_source),force,velocity,fields,stress

    def solve_force_coupled(self, body_force_n_m3, base_velocity_m_s, traction_pa,
                           boundary_modes_m, external_generalized_force_j,
                           external_resistance_j_s, *, coupling_source,
                           parent_state_id, epoch_id, time_s, force_source,
                           boundary_source, extra_stress_pa=None,
                           stress_source='explicit-zero-extra-stress', cancel=None):
        """Solve regional resistance and supplied exterior driving together.

        Each mode is a nodal displacement field in metres; its unknown rate is
        s^-1. Thus velocity=base+sum(mode*rate), conjugate force has units J,
        and force*rate is W (rotation modes give the usual torque/power pair).
        External resistance is a supplied symmetric positive-semidefinite J s
        matrix for physics OUTSIDE this region, never a second regional drag.
        This finite-mode coupling is not the unimplemented spherical mapper.
        """
        with self._operation(cancel):
            _name(coupling_source,'coupling source')
            meta,force,velocity,tractions,stress = self._request(
                body_force_n_m3,base_velocity_m_s,traction_pa,parent_state_id,
                epoch_id,time_s,force_source,boundary_source,extra_stress_pa,stress_source)
            raw = np.asarray(boundary_modes_m)
            if raw.ndim != 3 or not 1 <= raw.shape[0] <= 12:
                raise TectonicsError('one to twelve explicit coupling modes required')
            n = raw.shape[0]
            modes = _array(raw,(n,self._mesh.nv,3),'boundary displacement modes')
            drive = _array(external_generalized_force_j,(n,),'generalized driving force')
            drag = _array(external_resistance_j_s,(n,n),'exterior resistance')
            drag_scale = max(float(np.max(np.abs(drag))),np.finfo(float).tiny)
            if (np.max(np.abs(drag-drag.T)) > 1e-12*drag_scale
                    or np.linalg.eigvalsh((drag+drag.T)/2)[0] < -1e-12*drag_scale):
                raise TectonicsError('exterior resistance must be symmetric positive semidefinite')
            L,V = self._scales.length_m,self._scales.velocity_m_s
            modes_d = _factored_scale(modes,(),(L,),'scaled displacement modes')
            f,d,t,s,body,natural,load = self._scaled_request(force,velocity,tractions,stress)
            mean = 0. if self._mean is None else float(_factored_scale(np.asarray(self._mean),
                (L,),(self._eta0,V),'pressure datum'))
            requested = self._requested(f,d,t,s)
            # A pressure datum projects to exactly zero on the (necessarily
            # net-flux-free) coupling modes; keep it out of the coupling solve so
            # a large datum adds no round-off to the rates. It is published below.
            _,_,base_r,_,_,_,_ = self._linear(load,d,0.,cancel,requested)
            force_conversion = lambda r: _factored_scale(r,(self._eta0,V,L),(),'reaction force')
            q0 = np.einsum('mij,ij->m',modes,force_conversion(base_r))
            mode_key = _digest_array(modes)
            if self._mode_cache is not None and self._mode_cache[0] == mode_key:
                response = self._mode_cache[1]
                self._stats['coupling_response_hits'] += 1
            else:
                response = np.empty((n,n))
                zero_load = np.zeros(3*self._mesh.nv)
                for j in range(n):
                    _cancel(cancel)
                    _,_,r,_,_,_,_ = self._linear(zero_load,modes_d[j],0.,cancel)
                    response[:,j] = np.einsum('mij,ij->m',modes,force_conversion(r))
                response = frozen(response)
            scale = max(np.max(np.abs(response)),np.finfo(float).tiny)
            if np.max(np.abs(response-response.T)) > 2e-8*scale:
                raise TectonicsError('regional coupling violates reciprocal mechanical work')
            drag_matrix = _factored_scale(drag,(V,),(L,),'scaled exterior resistance')
            matrix = response+drag_matrix
            eig = np.linalg.eigvalsh((matrix+matrix.T)/2)
            if eig[0] <= 1e-12*max(np.max(np.abs(eig)),np.finfo(float).tiny):
                raise TectonicsError('coupled motion lacks independent resisting constraints')
            amplitudes = np.linalg.solve(matrix,drive-q0)
            prescribed = d+np.einsum('m,mij->ij',amplitudes,modes_d)
            u,p,r,error,count,momentum,datum = self._linear(load,prescribed,mean,cancel,requested)
            rates = _factored_scale(amplitudes,(V,),(L,),'generalized rates')
            regional_force = np.einsum('mij,ij->m',modes,force_conversion(r))
            exterior_force = drag@rates
            residual = regional_force+exterior_force-drive
            relative = np.linalg.norm(residual,np.inf)/max(np.linalg.norm(drive,np.inf),
                np.linalg.norm(regional_force,np.inf),np.linalg.norm(exterior_force,np.inf),np.finfo(float).tiny)
            if not np.all(np.isfinite(residual)) or relative > 5e-8:
                raise TectonicsError('global/regional force balance did not converge')
            meta['coupling'] = dict(source=coupling_source, modes_sha256=mode_key,
                external_force_sha256=_digest_array(drive),external_resistance_sha256=_digest_array(drag),
                force_relative_residual=float(relative), mode_count=n,
                convention='mode[m]*rate[1/s]=velocity[m/s]; generalized_force[J]*rate[1/s]=power[W]')
            base = self._result(u,p,r,s,body,natural,load,momentum,meta,error,count,datum)
            arrays = {name:base.array(name) for name in base.array_names}
            arrays.update(generalized_rates_s_inv=rates,generalized_regional_force_j=regional_force,
                          generalized_external_force_j=drive,generalized_drag_force_j=exterior_force,
                          generalized_force_residual_j=residual)
            result = RegionalMechanicalSnapshot(base.descriptor(),arrays)
            _cancel(cancel)
            self._verify()
            self._mode_cache = (mode_key,response)
            self._stats['solves'] += 1
            return result

    def _requested(self, f, d, t, s):
        """Whether any scaled input is nonzero (an all-zero assembly then underflowed)."""
        return bool(np.any(f) or np.any(s) or np.any(d.ravel()[self._fixed])
                    or any(np.any(a) for a in t.values()))

    def _scaled_request(self, force, velocity, tractions, stress):
        L,V = self._scales.length_m,self._scales.velocity_m_s
        f = _factored_scale(force,(L,L),(self._eta0,V),'body force')
        d = _factored_scale(velocity,(),(V,),'velocity')
        s = _factored_scale(stress,(L,),(self._eta0,V),'extra stress')
        t = {side:_factored_scale(a,(L,),(self._eta0,V),'traction') for side,a in tractions.items()}
        body = self._mesh.load(f)
        natural = sum((self._mesh.integrate_boundary_traction(side,a) for side,a in t.items()),
                      start=np.zeros(3*self._mesh.nv))
        load = self._mesh.load(f,extra_stress=s)+natural
        return f,d,t,s,body,natural,load

    def _work_roundoff(self, u, p, r, extra, load, body, natural, pressure_q, viscous):
        """Binary64 round-off bound of the work identity.

        Bounded by the magnitudes of the terms actually multiplied and summed
        (|A||u|, |B^T||p|, loads and reactions; quadrature powers use a 4/h
        per-node shape-derivative bound), times 64 units of round-off. Nothing
        here is an absolute floor, so rescaling the problem cannot bypass it.
        ``viscous`` is |A||u| (assembled entries) of this same solution.
        """
        ua = np.abs(u.ravel())
        operands = float(ua@viscous+np.abs(p)@(_magnitude(self._B)@ua)
                         +ua@(np.abs(load)+np.abs(body)+np.abs(natural)+np.abs(r.ravel())))
        gradient_bound = 108/float(np.min(self._mesh._spacing))*np.max(
            np.abs(u)[self._mesh.velocity_cells], axis=(1, 2))
        quadrature = float(np.sum(gradient_bound[:, None]*(np.sum(np.abs(extra), axis=(-2, -1))
                                                           +3*np.abs(pressure_q))*self._mesh.quadrature_weights))
        return 64*_EPS*(operands+quadrature)

    def _result(self,u,p,r,extra,body,natural,load,momentum,metadata,error,count,datum):
        mesh = self._mesh
        values = mesh.evaluate(u,p)
        gradient = values['gradient_q']
        D = (gradient+gradient.swapaxes(-1,-2))/2
        eta = _factored_scale(self._eta,(),(self._eta0,),'viscosity')
        viscous = 2*eta[...,None,None]*D
        stress = viscous+extra
        div = np.trace(gradient,axis1=-2,axis2=-1)
        weights = mesh.quadrature_weights
        viscous_power = float(np.sum(np.einsum('eqij,eqij->eq',viscous,D)*weights))
        extra_power = float(np.sum(np.einsum('eqij,eqij->eq',extra,D)*weights))
        pressure_power = -float(np.sum(values['pressure_q']*div*weights))
        body_power,natural_power,reaction_power = float(u.ravel()@body),float(u.ravel()@natural),float(np.sum(u*r))
        work_error = (viscous_power+extra_power+pressure_power-body_power-natural_power-reaction_power)
        # In exact arithmetic work_error is u_free.(momentum residual), which the
        # blockwise linear gate already bounds; subtracting it leaves what this
        # identity uniquely checks: consistency of the evaluated stresses,
        # divergence and powers with the assembled operators, up to round-off.
        # Scale by the larger side of the identity, never by max(1, ...); a rigid
        # or exactly balanced state (near-zero powers) keeps the round-off floor.
        work_error -= math.fsum(u.ravel()*momentum)
        work_scale = max(abs(viscous_power)+abs(extra_power)+abs(pressure_power),
                         abs(body_power)+abs(natural_power)+abs(reaction_power))
        work_scale += self._work_roundoff(u,p,r,extra,load,body,natural,values['pressure_q'],
                                          datum['viscous_magnitude'])/5e-9
        if not (math.isfinite(work_scale) and math.isfinite(work_error)):
            raise TectonicsError('3D mechanical work is outside binary64 range; '
                                 'choose RegionalMechanicsScales near the problem magnitudes')
        if work_scale == 0.:
            if error['forced']:
                raise TectonicsError('3D mechanical work underflows to zero; '
                                     'choose RegionalMechanicsScales near the problem magnitudes')
            work_relative = 0. if work_error == 0. else math.inf
        elif work_scale < _TINY/_EPS:
            raise TectonicsError('3D mechanical work is below binary64 relative precision; '
                                 'choose RegionalMechanicsScales near the problem magnitudes')
        else:
            work_relative = abs(work_error)/work_scale
        if not work_relative <= 5e-9:
            raise TectonicsError('3D mechanical work identity failed')
        L,V = self._scales.length_m,self._scales.velocity_m_s
        stress_scale = ((self._eta0,V),(L,))
        force_scale = ((self._eta0,V,L),())
        power_scale = ((self._eta0,V,V,L),())
        convert = lambda a, scale, label: _factored_scale(np.asarray(a),*scale,label)
        arrays = dict(velocity_m_s=convert(u,((V,),()),'velocity'),
            velocity_q_m_s=convert(values['velocity_q'],((V,),()),'quadrature velocity'),
            velocity_gradient_s_inv=convert(gradient,((V,),(L,)),'velocity gradient'),
            relative_pressure_pa=convert(p+datum['mean'],stress_scale,'pressure'),
            extra_plus_viscous_stress_pa=convert(stress,stress_scale,'stress'),
            velocity_constraint_reaction_n=convert(r+datum['reaction'],force_scale,'reaction'),
            natural_boundary_force_n=convert(natural.reshape(-1,3),force_scale,'natural force'))
        if self._physical:
            arrays['physical_pressure_pa'] = arrays['relative_pressure_pa']
        powers = {name:float(convert(a,power_scale,name)) for name,a in dict(
            viscous_dissipation=viscous_power,extra_stress_work=extra_power,
            pressure_work=pressure_power,body_work=body_power,
            prescribed_traction_work=natural_power,velocity_constraint_work=reaction_power).items()}
        data = dict(schema='atlas.regional3d-snapshot.v1', plan_id=self.plan_id,
            plan=self._definition, request=metadata, physical_pressure_defined=self._physical,
            numerical_pressure_gauge='volume-weighted mean' if self._gauge else 'natural traction',
            velocity_dofs=3*mesh.nv, pressure_dofs=mesh.np,
            weak_divergence_max=float(np.max(np.abs(self._B@u.ravel())/self._pw)),
            quadrature_divergence_l2=float(np.sqrt(np.sum(div*div*weights))),
            linear_relative_residual=error['linear'],momentum_backward_error=error['momentum'],
            continuity_backward_error=error['continuity'],linear_refinements=error['refinements'],
            work_relative_residual=work_relative,
            krylov_iterations=count,power_w=powers, scientific_acceptance=False,
            scope='same-time regional mechanical solve; no material/history advancement or boundary birth')
        return RegionalMechanicalSnapshot(data,arrays)

    def close(self):
        if getattr(self,'_active',False):
            raise TectonicsError('cannot close an active regional operation')
        if getattr(self,'_closed',True):
            return
        self._closed = True
        if self._mg is not None:
            self._stats['preconditioner_applications'] = self._mg.applications
        self._factor = self._P = self._K = self._A = self._B = self._Af = self._Bf = None
        self._mesh = self._latest = self._mode_cache = self._mg = self._shared = None
        self._context = None
        for guard in reversed(self._reservations):
            guard.__exit__(None,None,None)
        self._reservations.clear()

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self,*_):
        self.close()
