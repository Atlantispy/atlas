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
from pathlib import Path
import threading
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres, spilu, splu

from . import regional_elements3d as elements3d
from ._validation import TectonicsError, scalar, frozen
from .regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from .resources import select_budget, MemoryLimitError
from .reuse import ExecutionContext
from .stokes_execution import _native_lease, _factored_scale

SIDES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


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


class PreparedRegionalStokes3D:
    """Prepared heterogeneous finite-box solver with bounded reusable factors.

    ``boundary_types`` explicitly maps each side to three velocity/traction
    strings, in x,y,z order. Velocity input is one shared nodal array, so corners
    cannot acquire conflicting copies. Traction input uses face Gauss samples.
    Only the latest immutable solution is cached. Caller-held results are caller
    storage, not retained by an unbounded history. A changed material needs a new
    plan. ``gmres`` is the normal path; ``direct`` is an explicitly bounded check.
    """
    def __init__(self, cells, lengths_m, viscosity_pa_s, boundary_types, *,
                 scales, reference_viscosity_pa_s, frame_id, vertical_datum,
                 material_source, physical_mean_pressure_pa=None, method='gmres',
                 budget=None, cancel=None):
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
        if method not in ('gmres', 'direct'):
            raise TectonicsError('select gmres or explicit direct method')
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
        self._reservations = []
        self._resource = select_budget(budget)
        self._scales, self._eta0 = scales, eta0
        self._lengths, self._pattern = lengths, pattern
        self._method = method
        self._stats = dict(solves=0, result_hits=0, coupling_response_hits=0,
                           factorizations=0, krylov_iterations=0)
        nc = int(np.prod(cells))
        nv = int(np.prod(2*np.asarray(cells)+1))
        np_ = int(np.prod(np.asarray(cells)+1))
        # Conservative sparse assembly, work arrays and result envelope; allocator
        # overhead and caller buffers are not an operating-system RSS guarantee.
        self._retain(8*1024**2+420000*nc+3000*(3*nv+np_), 'regional3d-assembly')
        try:
            _cancel(cancel)
            import sys
            self._modules = (sys.modules[__name__], elements3d)
            for module in self._modules:
                if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != module._LOADED_SOURCE_SHA256:
                    raise TectonicsError('3D source changed since import; restart the process')
            self._tokens = tuple(_local_tokens(m) for m in self._modules)
            self._context = ExecutionContext('scipy')
            self._context_id = self._context.identity
            dimension = _factored_scale(np.asarray(lengths), (), (scales.length_m,), 'scaled box')
            self._mesh = elements3d.TaylorHoodBox(tuple(cells), tuple(dimension))
            mesh = self._mesh
            self._eta = _array(viscosity_pa_s, (nc, 27), 'quadrature viscosity', scalar_ok=True, positive=True)
            eta = _factored_scale(self._eta, (), (eta0,), 'scaled viscosity')
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
            self._Af = self._A[self._free][:, self._free].tocsc()
            self._Bf = self._B[:, self._free].tocsr()
            pressure_leak = np.asarray(self._Bf.T@np.ones(mesh.np)).ravel()
            self._gauge = bool(np.linalg.norm(pressure_leak, np.inf) < 1e-12*max(1., np.max(np.abs(self._B.data))))
            if physical_mean_pressure_pa is not None:
                physical_mean_pressure_pa = scalar(physical_mean_pressure_pa, 'physical mean pressure')
                if not self._gauge:
                    raise TectonicsError('normal traction already fixes pressure; a second datum is forbidden')
            self._physical = not self._gauge or physical_mean_pressure_pa is not None
            self._mean = physical_mean_pressure_pa
            self._w = self._pw/np.sum(self._pw)
            if self._gauge:
                w = sparse.csc_matrix(self._w[:, None])
                self._K = sparse.bmat([[self._Af, self._Bf.T, None],
                                      [self._Bf, None, w], [None, w.T, None]], format='csc')
            else:
                self._K = sparse.bmat([[self._Af, self._Bf.T], [self._Bf, None]], format='csc')
            if method == 'direct':
                allowance = 16*self._K.shape[0]**2+1024*self._K.shape[0]
            else:
                allowance = 16*10*self._Af.nnz+1024*self._Af.shape[0]
            self._retain(allowance, 'regional3d-factor')
            with _native_lease():
                _cancel(cancel)
                self._factor = (splu(self._K, permc_spec='COLAMD') if method == 'direct'
                                else spilu(self._Af, drop_tol=1e-4, fill_factor=8., permc_spec='COLAMD'))
            if _sparse_bytes(self._factor.L)+_sparse_bytes(self._factor.U) > allowance:
                raise MemoryLimitError('realised factor exceeded admitted factor allowance')
            self._stats['factorizations'] = 1
            self._P = LinearOperator(self._K.shape, matvec=self._precondition, dtype=float) if method == 'gmres' else None
            self._definition = dict(schema='atlas.regional3d-plan.v1', cells=list(cells),
                lengths_m=list(lengths), scales=asdict(scales), reference_viscosity_pa_s=eta0,
                viscosity_sha256=_digest_array(self._eta), boundary_types=pattern,
                frame_id=frame_id, vertical_datum=vertical_datum, material_source=material_source,
                physical_mean_pressure_pa=physical_mean_pressure_pa, method=method,
                linear_rtol=1e-11, pressure_gauge_required=self._gauge,
                element='Q2/Q1 tensor-product hexahedron; 3-point Gauss in each direction',
                coordinates='Cartesian right-handed x,y horizontal; z up from box bottom',
                execution=self._context_id)
            self.plan_id = _hash(self._definition)
            self._verify()
            self._stats['prepare_seconds'] = perf_counter()-start
        except BaseException:
            self.close()
            raise

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

    def statistics(self):
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

    def _linear(self, load, prescribed, mean, cancel):
        d = prescribed.ravel()[self._fixed]
        lift = np.zeros(3*self._mesh.nv)
        lift[self._fixed] = d
        if self._gauge:
            flux = float(np.sum(self._B@lift))
            scale = max(1., np.max(np.abs(d)))*sum(np.prod(self._mesh.lengths)/np.asarray(self._mesh.lengths))
            if abs(flux) > 2e-11*scale:
                raise TectonicsError('incompressible closed-boundary velocity has nonzero net flux')
        rv = (load-self._A@lift)[self._free]
        rp = -self._B@lift
        rhs = np.r_[rv, rp, mean] if self._gauge else np.r_[rv, rp]
        _cancel(cancel)
        if self._method == 'direct':
            x = self._factor.solve(rhs)
            count = 0
        else:
            count = 0
            def callback(_):
                nonlocal count
                count += 1
                _cancel(cancel)
            x, info = gmres(self._K, rhs, M=self._P, rtol=1e-11, atol=1e-13,
                            restart=60, maxiter=1200, callback=callback, callback_type='legacy')
            if info != 0:
                raise TectonicsError('3D GMRES did not converge; no silent direct fallback')
        _cancel(cancel)
        if not np.all(np.isfinite(x)):
            raise TectonicsError('nonfinite 3D solve')
        error = np.linalg.norm(self._K@x-rhs, np.inf)/max(1., np.linalg.norm(rhs, np.inf))
        if error > 2e-9:
            raise TectonicsError('3D linear residual exceeds fixed acceptance tolerance')
        nf = len(self._free)
        u = lift
        u[self._free] = x[:nf]
        p = x[nf:nf+self._mesh.np]
        reaction = self._A@u+self._B.T@p-load
        # Free equations carry numerical residual, not externally applied force.
        constrained_reaction = np.zeros_like(reaction)
        constrained_reaction[self._fixed] = reaction[self._fixed]
        self._stats['krylov_iterations'] += count
        return u.reshape(-1, 3), p, constrained_reaction.reshape(-1, 3), error, count

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
            u,p,r,error,count = self._linear(load,d,mean,cancel)
            result = self._result(u,p,r,s,body,natural,metadata,error,count)
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
            _,d,_,s,body,natural,load = self._scaled_request(force,velocity,tractions,stress)
            mean = 0. if self._mean is None else float(_factored_scale(np.asarray(self._mean),
                (L,),(self._eta0,V),'pressure datum'))
            _,_,base_r,_,_ = self._linear(load,d,mean,cancel)
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
                    _,_,r,_,_ = self._linear(zero_load,modes_d[j],0.,cancel)
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
            u,p,r,error,count = self._linear(load,prescribed,mean,cancel)
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
            base = self._result(u,p,r,s,body,natural,meta,error,count)
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

    def _result(self,u,p,r,extra,body,natural,metadata,error,count):
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
        work_scale = max(1.,abs(viscous_power)+abs(extra_power)+abs(pressure_power),
                         abs(body_power)+abs(natural_power)+abs(reaction_power))
        if abs(work_error)/work_scale > 5e-9:
            raise TectonicsError('3D mechanical work identity failed')
        L,V = self._scales.length_m,self._scales.velocity_m_s
        stress_scale = ((self._eta0,V),(L,))
        force_scale = ((self._eta0,V,L),())
        power_scale = ((self._eta0,V,V,L),())
        convert = lambda a, scale, label: _factored_scale(np.asarray(a),*scale,label)
        arrays = dict(velocity_m_s=convert(u,((V,),()),'velocity'),
            velocity_q_m_s=convert(values['velocity_q'],((V,),()),'quadrature velocity'),
            velocity_gradient_s_inv=convert(gradient,((V,),(L,)),'velocity gradient'),
            relative_pressure_pa=convert(p,stress_scale,'pressure'),
            extra_plus_viscous_stress_pa=convert(stress,stress_scale,'stress'),
            velocity_constraint_reaction_n=convert(r,force_scale,'reaction'),
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
            linear_relative_residual=error,work_relative_residual=abs(work_error)/work_scale,
            krylov_iterations=count,power_w=powers, scientific_acceptance=False,
            scope='same-time regional mechanical solve; no material/history advancement or boundary birth')
        return RegionalMechanicalSnapshot(data,arrays)

    def close(self):
        if getattr(self,'_active',False):
            raise TectonicsError('cannot close an active regional operation')
        if getattr(self,'_closed',True):
            return
        self._closed = True
        self._factor = self._P = self._K = self._A = self._B = self._Af = self._Bf = None
        self._mesh = self._latest = self._mode_cache = None
        self._context = None
        for guard in reversed(self._reservations):
            guard.__exit__(None,None,None)
        self._reservations.clear()

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self,*_):
        self.close()
