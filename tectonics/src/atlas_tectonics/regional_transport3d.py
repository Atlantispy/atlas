"""Conservative fixed-box 3D transport of extensive material inventories.

Q2 face samples are reconstructed from actual nodal velocity. An explicitly
bounded interior-face projection supplies locally conservative volume fluxes;
boundary velocity samples never change. Donor-cell advection is first order,
with separate opposite face streams and finite exterior stocks. Scalar history
carriage is not an objective elastic-stress update or a constitutive law.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
import sys
import threading

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from ._validation import TectonicsError, frozen, input_shape, scalar
from .regional_execution3d import _local_tokens
from .resources import select_budget, MemoryLimitError
from .reuse import ExecutionContext
from .stokes_execution import _native_lease

SIDES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _name(value):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise TectonicsError('nonempty bounded source/tracer name required')
    return value


def _cancel(cancel):
    if cancel is None:
        return
    if not callable(cancel) and not callable(getattr(cancel, 'is_set', None)):
        raise TectonicsError('cancellation must be a callable or Event')
    if cancel() if callable(cancel) else cancel.is_set():
        raise CancelledError('3D transport cancelled')


def _array(value, shape, name, *, nonnegative=False, broadcast=False):
    actual = input_shape(value, name)
    if not broadcast and actual != shape:
        raise TectonicsError(name+' has incorrect shape')
    try:
        a = np.asarray(value, dtype=float)
        a = np.broadcast_to(a, shape) if broadcast else a
    except (ValueError, TypeError, OverflowError) as exc:
        raise TectonicsError(name+' has incorrect numeric support') from exc
    if a.shape != shape or not np.isfinite(a).all() or (nonnegative and np.any(a < 0)):
        raise TectonicsError(name+' has nonfinite/negative data or incorrect shape')
    return frozen(a)


def _tracers(values, shape):
    if type(values) is not dict or len(values) > 64:
        raise TectonicsError('at most 64 named extensive scalar-history arrays required')
    return {_name(k): _array(v, shape, 'tracer '+k) for k, v in sorted(values.items())}


def _sum(a):
    return math.fsum(np.asarray(a).flat)


class _Arrays:
    """Detached immutable arrays and a detached JSON descriptor."""
    def __init__(self, metadata, arrays):
        object.__setattr__(self, '_metadata', _json(metadata))
        object.__setattr__(self, '_arrays', MappingProxyType({k: frozen(v) for k, v in arrays.items()}))
        h = hashlib.sha256(self._metadata)
        for k, v in sorted(self._arrays.items()):
            h.update(_json([k, v.shape])); h.update(v.tobytes())
        object.__setattr__(self, 'result_id', h.hexdigest())

    def __setattr__(self, key, value):
        raise AttributeError('transport results are immutable')

    @property
    def array_names(self):
        return tuple(self._arrays)

    def array(self, name):
        return self._arrays[name]

    def descriptor(self):
        return json.loads(self._metadata)


class ConservativeFaceFlow3D(_Arrays):
    @property
    def flow_id(self):
        return self.result_id


class FiniteBoundaryStock3D(_Arrays):
    """Finite per-face upstream stock; exports are accounted separately.

    Volume is m3, component masses kg, enthalpy J, tracers M*a. A zero-volume
    stock must have zero extensive inventories. Empty stock admits no inflow.
    """
    def __init__(self, volume_m3, component_mass_kg, enthalpy_j, material_tracers=None):
        shape = input_shape(volume_m3)
        mshape = input_shape(component_mass_kg)
        if len(shape) != 2 or len(mshape) != 3 or mshape[1:] != shape or not 1 <= mshape[0] <= 256:
            raise TectonicsError('boundary stock requires face arrays and 1..256 component inventories')
        volume = _array(volume_m3, shape, 'stock volume', nonnegative=True)
        mass = _array(component_mass_kg, mshape, 'stock mass', nonnegative=True)
        heat = _array(enthalpy_j, shape, 'stock enthalpy')
        tracers = _tracers({} if material_tracers is None else material_tracers, shape)
        empty = volume == 0
        if np.any(mass[:, empty] != 0) or np.any(heat[empty] != 0) or any(np.any(a[empty] != 0) for a in tracers.values()):
            raise TectonicsError('zero-volume stock cannot contain extensive inventories')
        super().__init__(dict(schema='atlas.regional3d-boundary-stock.v1', shape=shape,
            ncomponents=mshape[0], tracer_names=list(tracers)),
            dict(volume_m3=volume, component_mass_kg=mass, enthalpy_j=heat,
                 **{'tracer:'+k: a for k, a in tracers.items()}))


class TransportAdvance3D(_Arrays):
    def __init__(self, metadata, arrays, boundary_stocks, exports):
        super().__init__(metadata, arrays)
        object.__setattr__(self, 'boundary_stocks', MappingProxyType(dict(boundary_stocks)))
        object.__setattr__(self, 'exports', MappingProxyType(dict(exports)))


class PreparedRegionalTransport3D:
    """Single-owner prepared projection; no evolving state or result cache.

    Cells and arrays use x,y,z order with z fastest. Correction allowances are
    caller-declared method controls, never inferred from the supplied velocity.
    The relative correction is max(abs(delta normal velocity))/max(abs(raw)).
    """
    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise AttributeError('prepared transport definition is immutable')
        object.__setattr__(self, key, value)

    def __init__(self, cells, lengths_m, *, divergence_rtol,
                 max_velocity_correction_m_s, max_relative_correction,
                 budget=None, cancel=None):
        if type(cells) not in (tuple, list) or len(cells) != 3 or any(type(n) is not int or not 2 <= n <= 24 for n in cells):
            raise TectonicsError('three integer cell counts in [2,24] required')
        if input_shape(lengths_m) != (3,):
            raise TectonicsError('three positive physical lengths required')
        self.cells = tuple(cells)
        self.lengths_m = tuple(scalar(x, 'length', positive=True) for x in lengths_m)
        self.divergence_rtol = scalar(divergence_rtol, 'divergence tolerance', positive=True)
        if self.divergence_rtol >= 1e-6:
            raise TectonicsError('divergence_rtol must be below 1e-6')
        self.max_velocity_correction_m_s = scalar(max_velocity_correction_m_s, 'absolute correction allowance', nonnegative=True)
        self.max_relative_correction = scalar(max_relative_correction, 'relative correction allowance', nonnegative=True)
        self._spacing = np.asarray(self.lengths_m)/cells
        self.volume_m3 = float(np.prod(self._spacing))
        self._areas = np.asarray([np.prod(np.delete(self._spacing, a)) for a in range(3)])
        if (not math.isfinite(self.volume_m3) or self.volume_m3 <= 0 or
                not np.isfinite(self._areas).all() or np.any(self._areas <= 0)):
            raise TectonicsError('unrepresentable transport geometry')
        self._budget = select_budget(budget)
        self._owner = threading.get_ident(); self._active = False; self._closed = False
        self._guard = self._factor = self._context = None
        self._nc = math.prod(cells)
        # Sparse fill and transient construction allowance, checked against the
        # realised factor. This is byte admission, not an operating-system cap.
        self._allowance = 2*1024**2+8192*self._nc
        try:
            _cancel(cancel)
            guard = self._budget.reserve(self._allowance, category='regional3d-transport-plan')
            guard.__enter__(); self._guard = guard
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
                raise TectonicsError('transport source changed since import; restart the process')
            self._tokens = _local_tokens(sys.modules[__name__])
            self._context = ExecutionContext('scipy')
            rows = []; cols = []; signs = []; self._parts = []; weights = []; count = 0
            indices = np.arange(self._nc).reshape(self.cells)
            for axis in range(3):
                _cancel(cancel)
                lo = [slice(None)]*3; hi = lo.copy(); lo[axis] = slice(None, -1); hi[axis] = slice(1, None)
                left, right = indices[tuple(lo)].ravel(), indices[tuple(hi)].ravel()
                n = len(left); ids = np.arange(count, count+n)
                rows.extend((left, right)); cols.extend((ids, ids)); signs.extend((np.ones(n), -np.ones(n)))
                self._parts.append((axis, count, count+n)); count += n
                weights.append(np.full(n, self._areas[axis]/self._spacing[axis]))
            self._inverse_weight = np.concatenate(weights)
            if not np.isfinite(self._inverse_weight).all() or np.any(self._inverse_weight <= 0):
                raise TectonicsError('unrepresentable projection metric')
            self._B = sparse.csr_matrix((np.concatenate(signs), (np.concatenate(rows), np.concatenate(cols))), shape=(self._nc, count))
            lap = (self._B@sparse.diags(self._inverse_weight)@self._B.T).tocsc()
            with _native_lease():
                self._factor = splu(lap[1:, 1:], permc_spec='COLAMD')
            actual = sum(a.data.nbytes+a.indices.nbytes+a.indptr.nbytes for a in (self._B, self._factor.L, self._factor.U))
            if actual > self._allowance:
                raise MemoryLimitError('realised projection factor exceeded admitted allowance')
            points, weights = np.polynomial.legendre.leggauss(3)
            basis = np.stack((.5*points*(points-1), 1-points*points, .5*points*(points+1)), axis=1)
            self._face_basis = frozen(np.einsum('ai,bj->abij', basis, basis).reshape(9, 9))
            self._face_weights = frozen(np.outer(weights, weights).ravel()/4)
            self._definition = dict(schema='atlas.regional3d-transport-plan.v1', cells=self.cells,
                lengths_m=self.lengths_m, divergence_rtol=self.divergence_rtol,
                max_velocity_correction_m_s=self.max_velocity_correction_m_s,
                max_relative_correction=self.max_relative_correction,
                method='Q2 face Gauss; fixed-boundary weighted interior projection; first-order donor cell',
                execution=self._context.identity, field_order='x,y,z; z fastest',
                stress_evolution=False, moving_mesh=False)
            self.plan_id = hashlib.sha256(_json(self._definition)).hexdigest()
            self._verify()
        except BaseException:
            self.close(); raise

    def _verify(self):
        if self._closed:
            raise TectonicsError('transport plan is closed')
        if _local_tokens(sys.modules[__name__]) != self._tokens:
            raise TectonicsError('loaded transport implementation changed')
        self._context.verify()

    @contextmanager
    def _operation(self, cancel):
        if threading.get_ident() != self._owner or self._active:
            raise TectonicsError('transport plan is single-owner and non-reentrant')
        self._verify(); _cancel(cancel); self._active = True
        try:
            with _native_lease():
                yield
            _cancel(cancel); self._verify()
        finally:
            self._active = False

    def descriptor(self):
        self._verify(); return json.loads(_json(self._definition))

    def statistics(self):
        return dict(factorizations=1, budget=self._budget.statistics())

    def _shape(self, axis, *, side=False):
        shape = list(self.cells)
        if side:
            del shape[axis]
        else:
            shape[axis] += 1
        return tuple(shape)

    def empty_boundary_stocks(self, ncomponents, tracer_names=()):
        self._verify()
        if type(ncomponents) is not int or not 1 <= ncomponents <= 256:
            raise TectonicsError('1..256 components required')
        names = tuple(_name(k) for k in tracer_names)
        if len(names) > 64 or len(set(names)) != len(names):
            raise TectonicsError('unique bounded scalar-history names required')
        return {s: self.boundary_stock(s, 0., np.zeros(ncomponents), 0., {k: 0. for k in names}) for s in SIDES}

    def boundary_stock(self, side, volume_m3, component_mass_kg, enthalpy_j, material_tracers=None):
        self._verify()
        if side not in SIDES:
            raise TectonicsError('unknown boundary side')
        shape = self._shape('xyz'.index(side[0]), side=True)
        mshape = input_shape(component_mass_kg)
        if len(mshape) not in (1, 3) or not 1 <= mshape[0] <= 256:
            raise TectonicsError('component vector or component+face mass array required')
        mass = np.asarray(component_mass_kg)
        if len(mshape) == 1:
            mass = mass[:, None, None]
        tracers = {} if material_tracers is None else material_tracers
        if type(tracers) is not dict or len(tracers) > 64:
            raise TectonicsError('bounded tracer mapping required')
        return FiniteBoundaryStock3D(_array(volume_m3, shape, 'volume', nonnegative=True, broadcast=True),
            _array(mass, (mshape[0], *shape), 'mass', nonnegative=True, broadcast=True),
            _array(enthalpy_j, shape, 'enthalpy', broadcast=True),
            {_name(k): _array(v, shape, 'tracer', broadcast=True) for k, v in tracers.items()})

    def _sample_faces(self, velocity):
        samples = []
        for axis in range(3):
            a = np.moveaxis(velocity[..., axis], axis, 0)[::2]
            # axis is now normal; the remaining directions retain x,y,z order.
            windows = np.lib.stride_tricks.sliding_window_view(a, (3, 3), axis=(1, 2))[:, ::2, ::2]
            values = windows.reshape(*windows.shape[:3], 9)@self._face_basis.T
            samples.append(np.moveaxis(values, 0, axis))
        return samples

    def project_velocity(self, velocity_nodes_m_s, *, source_result_id, cancel=None):
        _name(source_result_id)
        shape = tuple(2*n+1 for n in self.cells)
        with self._operation(cancel), self._budget.reserve(4096*self._nc+65536, category='regional3d-face-projection'):
            v = _array(velocity_nodes_m_s, (math.prod(shape), 3), 'Q2 nodal velocity').reshape(*shape, 3)
            raw = self._sample_faces(v)
            flux = [np.sum(a*self._face_weights, axis=-1)*area for a, area in zip(raw, self._areas)]
            residual = sum(np.diff(f, axis=axis) for axis, f in enumerate(flux))
            boundary_abs = math.fsum(_sum(np.take(np.abs(a), j, axis=axis)*self._face_weights)*self._areas[axis]
                for axis, a in enumerate(raw) for j in (0, -1))
            raw_face_scale = max(float(np.max(np.sum(np.abs(a)*self._face_weights, axis=-1)*area))
                for a, area in zip(raw, self._areas))
            net = math.fsum(sign*_sum(np.take(f, j, axis=axis))
                for axis, f in enumerate(flux) for j, sign in ((0, -1.), (-1, 1.)))
            epsilon = np.finfo(float).eps
            if abs(net) > (self.divergence_rtol+256*epsilon)*boundary_abs:
                raise TectonicsError('global boundary volume flux is incompatible with incompressibility')
            # Interior corrections cannot remove global boundary roundoff. Keep
            # and report that mean instead of modifying boundary driving.
            rhs = -(residual.ravel()-_sum(residual)/self._nc)
            potential = np.zeros(self._nc)
            potential[1:] = self._factor.solve(rhs[1:])
            correction = self._inverse_weight*(self._B.T@potential)
            corrected = [a.copy() for a in raw]
            absolute = 0.
            for axis, start, stop in self._parts:
                _cancel(cancel)
                at = [slice(None)]*3; at[axis] = slice(1, -1)
                delta = correction[start:stop].reshape(corrected[axis][tuple(at)].shape[:-1])/self._areas[axis]
                corrected[axis][tuple(at)] += delta[..., None]
                absolute = max(absolute, float(np.max(np.abs(delta))))
            speed = max(float(np.max(np.abs(a))) for a in raw)
            relative = absolute/speed if speed else 0.
            if absolute > self.max_velocity_correction_m_s or relative > self.max_relative_correction:
                raise TectonicsError('transport velocity correction exceeds the declared allowance')
            arrays = {}; final_flux = []; sample_scale = 0.
            for axis, (old, new, area) in enumerate(zip(raw, corrected, self._areas)):
                label = 'xyz'[axis]
                positive = np.sum(np.maximum(new, 0)*self._face_weights, axis=-1)*area
                negative = np.sum(np.maximum(-new, 0)*self._face_weights, axis=-1)*area
                final_flux.append(positive-negative)
                sample_scale = max(sample_scale, float(np.max(positive+negative)))
                arrays.update({f'raw_normal_{label}_m_s': old, f'normal_{label}_m_s': new,
                    f'positive_{label}_m3_s': positive, f'negative_{label}_m3_s': negative,
                    f'net_{label}_m3_s': positive-negative})
            final_residual = sum(np.diff(f, axis=a) for a, f in enumerate(final_flux))
            maximum = float(np.max(np.abs(final_residual)))
            # A projected zero field still carries roundoff from the original
            # nonzero flux. Scale only the machine-precision floor by that work;
            # the caller's relative divergence allowance remains unchanged.
            roundoff_scale = max(boundary_abs, raw_face_scale)
            residual_limit = self.divergence_rtol*sample_scale+256*epsilon*roundoff_scale
            if not np.isfinite(final_residual).all() or maximum > residual_limit:
                raise TectonicsError('projected local volume continuity exceeds the declared tolerance')
            arrays['cell_net_volume_m3_s'] = final_residual
            meta = dict(schema='atlas.regional3d-face-flow.v1', plan_id=self.plan_id,
                source_result_id=source_result_id, raw_max_cell_net_m3_s=float(np.max(np.abs(residual))),
                corrected_max_cell_net_m3_s=maximum, corrected_max_divergence_s_inv=maximum/self.volume_m3,
                global_boundary_net_m3_s=net, boundary_absolute_flux_m3_s=boundary_abs,
                correction_max_m_s=absolute, correction_relative_max=relative,
                local_residual_limit_m3_s=residual_limit, roundoff_flux_scale_m3_s=roundoff_scale,
                boundary_samples_unchanged=True,
                signed_face_rule='exact Q2 integral; split opposite streams use 3x3 Gauss quadrature',
                source_status='WORKING NON-CANON', scientific_acceptance=False)
            return ConservativeFaceFlow3D(meta, arrays)

    def advect(self, component_mass_kg, enthalpy_j, material_tracers, flow, duration_s, *, boundary_stocks, cancel=None):
        """One atomic Euler donor-cell step; no sources, clipping or substeps."""
        dt = scalar(duration_s, 'transport duration', positive=True)
        mshape = input_shape(component_mass_kg)
        if len(mshape) != 4 or mshape[1:] != self.cells or not 1 <= mshape[0] <= 256:
            raise TectonicsError('component-first cell mass arrays required')
        if type(flow) is not ConservativeFaceFlow3D or flow.descriptor()['plan_id'] != self.plan_id:
            raise TectonicsError('face flow belongs to a different prepared transport plan')
        if not isinstance(boundary_stocks, (dict, MappingProxyType)) or set(boundary_stocks) != set(SIDES):
            raise TectonicsError('all six finite boundary stocks required')
        nt = len(material_tracers) if type(material_tracers) is dict else 65
        with self._operation(cancel), self._budget.reserve((mshape[0]+nt+2)*1024*self._nc+131072, category='regional3d-inventory-transport'):
            mass = _array(component_mass_kg, mshape, 'component mass', nonnegative=True)
            heat = _array(enthalpy_j, self.cells, 'enthalpy')
            tracers = _tracers(material_tracers, self.cells)
            fields = [('component_mass_kg', mass), ('enthalpy_j', heat)]+[('tracer:'+k, v) for k, v in tracers.items()]
            old = np.concatenate((mass, heat[None], *(v[None] for v in tracers.values())), axis=0)
            outgoing = np.zeros(self.cells); streams = []
            incoming = {}; exported_volume = {}; boundary_data = {}; remaining = {}; exports = {}
            for axis, label in enumerate('xyz'):
                pos, neg = (flow.array(f'{word}_{label}_m3_s')*dt for word in ('positive', 'negative'))
                if not np.isfinite(pos).all() or not np.isfinite(neg).all():
                    raise TectonicsError('unrepresentable swept face volume')
                streams.append((pos, neg))
                lo = [slice(None)]*3; hi = lo.copy(); lo[axis] = slice(None, -1); hi[axis] = slice(1, None)
                outgoing += pos[tuple(hi)]+neg[tuple(lo)]
                for end in (0, 1):
                    side = label+str(end); stock = boundary_stocks[side]
                    if type(stock) is not FiniteBoundaryStock3D:
                        raise TectonicsError('typed finite boundary stock required')
                    sd = stock.descriptor()
                    if tuple(sd['shape']) != self._shape(axis, side=True) or sd['ncomponents'] != mshape[0] or sd['tracer_names'] != list(tracers):
                        raise TectonicsError('boundary component/history support mismatch')
                    incoming[side] = np.take(pos if end == 0 else neg, 0 if end == 0 else -1, axis=axis)
                    exported_volume[side] = np.take(neg if end == 0 else pos, 0 if end == 0 else -1, axis=axis)
                    volume = stock.array('volume_m3')
                    if np.any(incoming[side] > volume):
                        raise TectonicsError('finite boundary stock exhausted by requested inflow')
                    if np.any((incoming[side] > 0) & (volume-incoming[side] == volume)):
                        raise TectonicsError('finite boundary stock debit is below representable volume resolution')
                    boundary_data[side] = np.concatenate((stock.array('component_mass_kg'), stock.array('enthalpy_j')[None],
                        *(stock.array('tracer:'+k)[None] for k in tracers)), axis=0)
            courant = outgoing/self.volume_m3
            if not np.isfinite(courant).all() or np.any(courant > 1.):
                raise TectonicsError('outgoing donor-volume CFL exceeds one; no automatic substeps')
            # Retained fractions plus incoming transfers avoid cancellation into
            # negative inventories at an exactly exhausted donor.
            new = old*(1-courant)[None]
            transfer_arrays = {}; boundary_out = {}; boundary_in = {}
            for axis, (pos, neg) in enumerate(streams):
                _cancel(cancel)
                label = 'xyz'[axis]; fshape = self._shape(axis)
                positive = np.zeros((old.shape[0], *fshape)); negative = np.zeros_like(positive)
                below = [slice(None)]*4; above = below.copy(); below[axis+1] = slice(None, -1); above[axis+1] = slice(1, None)
                positive[tuple(above)] = old*(np.take(pos, range(1, self.cells[axis]+1), axis=axis)/self.volume_m3)[None]
                negative[tuple(below)] = old*(np.take(neg, range(self.cells[axis]), axis=axis)/self.volume_m3)[None]
                for end in (0, 1):
                    side = label+str(end); stock = boundary_stocks[side]; volume = stock.array('volume_m3')
                    fraction = np.divide(incoming[side], volume, out=np.zeros_like(volume), where=volume > 0)
                    entry = boundary_data[side]*fraction[None]
                    face = [slice(None)]*4; face[axis+1] = 0 if end == 0 else -1
                    (positive if end == 0 else negative)[tuple(face)] = entry
                    exit_inventory = (negative if end == 0 else positive)[tuple(face)]
                    boundary_in[side] = entry; boundary_out[side] = exit_inventory
                    rem = boundary_data[side]*(1-fraction)[None]
                    remaining[side] = FiniteBoundaryStock3D(volume-incoming[side], rem[:mshape[0]], rem[mshape[0]],
                        {k: rem[mshape[0]+1+i] for i, k in enumerate(tracers)})
                    exports[side] = FiniteBoundaryStock3D(exported_volume[side], exit_inventory[:mshape[0]], exit_inventory[mshape[0]],
                        {k: exit_inventory[mshape[0]+1+i] for i, k in enumerate(tracers)})
                new += positive[tuple(below)]+negative[tuple(above)]
                transfer_arrays[label] = positive-negative
            if not np.isfinite(new).all() or np.any(new[:mshape[0]] < 0):
                raise TectonicsError('nonfinite or negative transported inventory')
            # Independently reconstruct the net cell change from returned face
            # transfers; scale each field by its own inventory, including traces.
            change = -sum(np.diff(a, axis=i+1) for i, a in enumerate(transfer_arrays.values()))
            local = new-old-change
            accounts = []; offset = 0; arrays = {}
            for key, initial in fields:
                count = mshape[0] if key == 'component_mass_kg' else 1
                final = new[offset:offset+count]
                arrays[key] = final if count > 1 or key == 'component_mass_kg' else final[0]
                for label, transfer in transfer_arrays.items():
                    part = transfer[offset:offset+count]
                    arrays[key+':transfer_'+label] = part if key == 'component_mass_kg' else part[0]
                for j in range(count):
                    index = offset+j
                    before, after = _sum(old[index]), _sum(new[index])
                    inflow = math.fsum(_sum(a[index]) for a in boundary_in.values())
                    outflow = math.fsum(_sum(a[index]) for a in boundary_out.values())
                    balance = math.fsum((after, -before, -inflow, outflow))
                    stock_before = math.fsum(_sum(a[index]) for a in boundary_data.values())
                    stock_after = math.fsum(_sum(remaining[s].array(key)[j] if key == 'component_mass_kg'
                        else remaining[s].array(key)) for s in SIDES)
                    closed_balance = math.fsum((after, stock_after, outflow, -before, -stock_before))
                    scale = max(_sum(np.abs(old[index])), _sum(np.abs(new[index])),
                        math.fsum(_sum(np.abs(a[index])) for a in boundary_in.values()),
                        math.fsum(_sum(np.abs(a[index])) for a in boundary_out.values()))
                    error = max(abs(balance), float(np.max(np.abs(local[index]))))
                    if error > 1e-10*scale:
                        raise TectonicsError('returned inventory/face-transfer account failed')
                    closed_scale = max(scale, math.fsum(_sum(np.abs(a[index])) for a in boundary_data.values()))
                    if abs(closed_balance) > 1e-10*closed_scale:
                        raise TectonicsError('domain plus finite boundary stock account failed')
                    accounts.append(dict(field=key, component=j if key == 'component_mass_kg' else None,
                        before=before, after=after, inflow=inflow, outflow=outflow,
                        balance_residual=balance, local_residual_max=float(np.max(np.abs(local[index]))),
                        boundary_stock_before=stock_before, boundary_stock_after=stock_after,
                        closed_balance_residual=closed_balance))
                offset += count
            metadata = dict(schema='atlas.regional3d-transport-advance.v1', plan_id=self.plan_id,
                flow_id=flow.flow_id, duration_s=dt, maximum_outgoing_courant=float(courant.max()),
                method='first-order conservative Euler donor-cell; paired opposite face streams',
                source_status='WORKING NON-CANON', scientific_acceptance=False,
                tracer_semantics='mass-weighted scalar histories M*a; no constitutive or objective stress update',
                enthalpy_unit='J', component_mass_unit='kg', accounts=accounts,
                input_boundary_stock_ids={s: boundary_stocks[s].result_id for s in SIDES},
                remaining_boundary_stock_ids={s: remaining[s].result_id for s in SIDES},
                export_ids={s: exports[s].result_id for s in SIDES})
            return TransportAdvance3D(metadata, arrays, remaining, exports)

    def close(self):
        if getattr(self, '_active', False):
            raise TectonicsError('cannot close active transport plan')
        if getattr(self, '_closed', True):
            return
        self._closed = True; self._factor = self._context = None
        if self._guard is not None:
            self._guard.__exit__(None, None, None); self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
