"""Bounded, source-bound backward-Euler heat conduction on a Cartesian box.

SPDX-License-Identifier: AGPL-3.0-only

Cell-centred finite volumes with constant volumetric heat capacity and isotropic
conductivity. Enthalpy is sensible heat c*V*T, in joules per cell, with no latent
heat or advection. A face flux is positive OUT of the box. Prescribed boundary
temperatures lie on the physical face, half a cell from its centre.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import contextmanager
import hashlib
import math
from pathlib import Path
import sys
import threading

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from ._validation import TectonicsError, scalar, input_shape, snapshot
from .regional_execution import RegionalMechanicalSnapshot
from . import regional_execution3d as mechanics3d
from .resources import select_budget, MemoryLimitError
from .reuse import ExecutionContext
from .stokes_execution import _native_lease, _factored_scale

SIDES = ('x0', 'x1', 'y0', 'y1', 'z0', 'z1')
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise CancelledError('3D regional heat advance cancelled')


def _field(value, shape, label, *, scalar_ok=False, positive=False):
    found = input_shape(value, label)
    if scalar_ok and not found:
        number = scalar(value, label, positive=positive)
        result = np.full(shape, number)
    elif found != shape:
        raise TectonicsError(label+' has incorrect shape')
    else:
        result = snapshot(value, label)
    if positive and np.any(result <= 0):
        raise TectonicsError(label+' must be strictly positive')
    return result


def _sum(values, label):
    try:
        result = math.fsum(np.asarray(values).ravel())
    except OverflowError as exc:
        raise TectonicsError(label+' is outside finite binary64 range') from exc
    if not math.isfinite(result):
        raise TectonicsError(label+' is outside finite binary64 range')
    return result


class PreparedRegionalHeat3D:
    """One-owner prepared diffusion plan with one reusable sparse LU factor.

    Arrays have shape ``(nx, ny, nz)``. Counts are positive integers, at most 64
    on each axis; the common WorkBudget must also admit assembly/work storage
    and a conservative dense upper envelope for the sparse factors BEFORE any
    grid allocation. The allowance is accounting, not an OS RSS guarantee.

    All six boundaries are explicit ``(kind, value)`` tuples. ``temperature``
    values are positive kelvin; ``flux`` values are signed outward W/m2. A value
    can be scalar or have the two remaining axes' cell shape in their original
    order. Sources are signed W/m3, scalar or cell-shaped, held constant over
    the supplied interval. No automatic subdivision, clipping or latent heat.

    The result uses the immutable named-array snapshot interface, with fields
    ``temperature_k`` and ``enthalpy_j``. Its descriptor includes the actual
    matrix residual and the source/each outward-boundary energy in joules.
    """

    def __init__(self, cells, lengths_m, heat_capacity_j_m3_k,
                 conductivity_w_m_k, *, budget=None):
        if (type(cells) not in (tuple, list) or len(cells) != 3
                or any(type(n) is not int or not 1 <= n <= 64 for n in cells)):
            raise TectonicsError('3D heat grid needs three integer cell counts from 1 to 64')
        if type(lengths_m) not in (tuple, list) or len(lengths_m) != 3:
            raise TectonicsError('three physical lengths required')
        lengths = tuple(scalar(v, 'length', positive=True) for v in lengths_m)
        capacity = scalar(heat_capacity_j_m3_k, 'volumetric heat capacity', positive=True)
        conductivity = scalar(conductivity_w_m_k, 'conductivity', positive=True)
        self._closed = False
        self._active = False
        self._owner = threading.get_ident()
        self._context = self._matrix = self._factor = self._factor_key = None
        self._diffusion = self._indices = None
        self._reservations = []
        self._resource = select_budget(budget)
        self._cells, self._lengths = tuple(cells), lengths
        self._capacity, self._conductivity = capacity, conductivity
        self._count = math.prod(cells)
        # Two triangular factors can be dense in the worst case. Charge their
        # indices, values and workspace conservatively before allocating a grid.
        self._factor_allowance = 24*self._count**2+1024*self._count
        self._stats = dict(advances=0, factorizations=0, factor_reuses=0)
        guard = self._resource.reserve(2*1024**2+2048*self._count+self._factor_allowance,
                                       category='regional-heat3d-plan')
        guard.__enter__()
        self._reservations.append(guard)
        try:
            self._modules = (sys.modules[__name__], mechanics3d)
            for module in self._modules:
                if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != module._LOADED_SOURCE_SHA256:
                    raise TectonicsError('3D heat source changed since import; restart the process')
            self._tokens = tuple(mechanics3d._local_tokens(m) for m in self._modules)
            self._context = ExecutionContext('scipy')
            self._context_id = self._context.identity
            self._spacing = tuple(_factored_scale(np.asarray([v]), (), (float(n),),
                                                   'cell spacing').item()
                                  for v, n in zip(lengths, cells))
            self._volume = _factored_scale(np.asarray([1.]), self._spacing, (), 'cell volume').item()
            self._cell_capacity = _factored_scale(np.asarray([capacity]),
                (self._volume,), (), 'cell heat capacity').item()
            self._areas = tuple(_factored_scale(np.asarray([1.]),
                tuple(self._spacing[j] for j in range(3) if j != axis), (), 'face area').item()
                for axis in range(3))
            self._rates = tuple(_factored_scale(np.asarray([conductivity]), (),
                (capacity, h, h), 'diffusion rate').item() for h in self._spacing)
            self._indices = np.arange(self._count).reshape(self._cells)
            self._faces = {}
            for side in SIDES:
                axis = 'xyz'.index(side[0])
                view = [slice(None)]*3
                view[axis] = 0 if side[1] == '0' else -1
                self._faces[side] = tuple(view)
            with _native_lease():
                self._diffusion = self._build_diffusion()
            self._definition = dict(schema='atlas.regional-heat3d-plan.v1',
                cells=list(cells), lengths_m=list(lengths),
                heat_capacity_j_m3_k=capacity, conductivity_w_m_k=conductivity,
                cell_volume_m3=self._volume, execution=self._context_id,
                method='cell-centred finite volume; backward Euler; sparse LU',
                boundary_convention='positive outward flux; face temperature at half-cell distance',
                enthalpy_convention='constant volumetric capacity times cell volume times kelvin',
                linear_relative_tolerance=1e-11, energy_relative_tolerance=1e-11,
                automatic_substeps=False)
            self.plan_id = mechanics3d._hash(self._definition)
            self._verify()
        except BaseException:
            self.close()
            raise

    def _build_diffusion(self):
        """Assemble each interior conductance once, with two equal opposites."""
        diagonal = np.zeros(self._count)
        rows, columns, data = [], [], []
        for axis, rate in enumerate(self._rates):
            low, high = [slice(None)]*3, [slice(None)]*3
            low[axis], high[axis] = slice(None, -1), slice(1, None)
            a, b = self._indices[tuple(low)].ravel(), self._indices[tuple(high)].ravel()
            diagonal[a] += rate
            diagonal[b] += rate
            rows.extend((a, b))
            columns.extend((b, a))
            data.extend((np.full(a.size, -rate), np.full(a.size, -rate)))
        flat = self._indices.ravel()
        rows.append(flat)
        columns.append(flat)
        data.append(diagonal)
        matrix = sparse.coo_matrix((np.concatenate(data),
            (np.concatenate(rows), np.concatenate(columns))), shape=(self._count, self._count)).tocsc()
        if not np.all(np.isfinite(matrix.data)):
            raise TectonicsError('3D heat diffusion matrix exceeds finite binary64 range')
        return matrix

    def _verify(self):
        if self._closed:
            raise TectonicsError('3D heat plan is closed')
        if tuple(mechanics3d._local_tokens(m) for m in self._modules) != self._tokens:
            raise TectonicsError('loaded 3D heat implementation changed')
        self._context.verify()

    @contextmanager
    def _operation(self, cancel):
        if threading.get_ident() != self._owner or self._active:
            raise TectonicsError('prepared 3D heat plan is single-owner and non-reentrant')
        self._verify()
        _cancel(cancel)
        self._active = True
        try:
            with _native_lease(), np.errstate(over='raise', invalid='raise', divide='raise'):
                try:
                    yield
                except FloatingPointError as exc:
                    raise TectonicsError('3D heat advance exceeds finite binary64 range') from exc
            _cancel(cancel)
            self._verify()
        finally:
            self._active = False

    def descriptor(self):
        self._verify()
        # Reuse the same canonical JSON representation as the regional solver.
        import json
        return json.loads(mechanics3d._json(self._definition))

    def statistics(self):
        return dict(self._stats, budget=self._resource.statistics())

    def _boundaries(self, boundaries):
        if type(boundaries) is not dict or set(boundaries) != set(SIDES):
            raise TectonicsError('all six thermal boundary sides must be declared')
        fields = {}
        for side in SIDES:
            item = boundaries[side]
            if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
                    or item[0] not in ('temperature', 'flux')):
                raise TectonicsError('thermal boundary needs a temperature/flux tuple')
            kind, value = item
            shape = tuple(self._cells[j] for j in range(3) if j != 'xyz'.index(side[0]))
            fields[side] = (kind, _field(value, shape, 'boundary '+side,
                                        scalar_ok=True, positive=kind == 'temperature'))
        return fields

    def _prepare_factor(self, duration, fields, cancel):
        kinds = tuple(fields[side][0] for side in SIDES)
        key = (duration, self._capacity, self._conductivity, kinds)
        if key == self._factor_key:
            self._stats['factor_reuses'] += 1
            return
        # Release the old native factor before building a replacement: retained
        # capacity covers ONE cache entry, never an accumulating duration cache.
        self._factor = self._matrix = self._factor_key = None
        matrix = self._diffusion.copy()
        matrix.data = _factored_scale(matrix.data, (duration,), (), 'time-scaled diffusion')
        diagonal = matrix.diagonal()+1.
        for side in SIDES:
            if fields[side][0] == 'temperature':
                axis = 'xyz'.index(side[0])
                indices = self._indices[self._faces[side]].ravel()
                diagonal[indices] += _factored_scale(np.asarray([self._rates[axis]]),
                    (2., duration), (), 'Dirichlet diagonal').item()
        matrix.setdiag(diagonal)
        matrix.eliminate_zeros()
        if not np.all(np.isfinite(matrix.data)):
            raise TectonicsError('3D heat matrix exceeds finite binary64 range')
        _cancel(cancel)
        try:
            factor = splu(matrix, permc_spec='COLAMD')
        except RuntimeError as exc:
            raise TectonicsError('3D heat factorisation failed at the supplied scale') from exc
        _cancel(cancel)
        if mechanics3d._sparse_bytes(factor.L)+mechanics3d._sparse_bytes(factor.U) > self._factor_allowance:
            raise MemoryLimitError('realised 3D heat factor exceeded admitted allowance')
        self._factor, self._matrix, self._factor_key = factor, matrix, key
        self._stats['factorizations'] += 1

    def advance(self, enthalpy_j, duration_s, boundaries, source_w_m3, *,
                source_id, cancel=None):
        """Advance exactly one requested interval; boundary/source data are fixed.

        The finite-volume equation is c*V*(Tnew-Told) = dt*(source*V -
        outward boundary power + interior neighbour conductances). No state is
        retained apart from geometry and the latest matrix factor.
        """
        with self._operation(cancel):
            mechanics3d._name(source_id, 'heat source')
            duration = scalar(duration_s, 'heat duration', positive=True)
            old = _field(enthalpy_j, self._cells, 'cell enthalpy', positive=True)
            sources = _field(source_w_m3, self._cells, 'volumetric heat source', scalar_ok=True)
            fields = self._boundaries(boundaries)
            rhs = _factored_scale(old, (), (self._cell_capacity,), 'initial temperature')
            rhs += _factored_scale(sources, (duration,), (self._capacity,), 'source temperature')
            for side, (kind, value) in fields.items():
                axis, face = 'xyz'.index(side[0]), self._faces[side]
                if kind == 'temperature':
                    rhs[face] += _factored_scale(value, (2., duration, self._rates[axis]),
                                                (), 'prescribed temperature contribution')
                else:
                    rhs[face] -= _factored_scale(value, (duration,),
                        (self._capacity, self._spacing[axis]), 'outward heat flux contribution')
            if not np.all(np.isfinite(rhs)):
                raise TectonicsError('nonfinite 3D heat right-hand side')
            self._prepare_factor(duration, fields, cancel)
            _cancel(cancel)
            temperature = self._factor.solve(rhs.ravel()).reshape(self._cells)
            _cancel(cancel)
            if not np.all(np.isfinite(temperature)) or np.any(temperature <= 0):
                raise TectonicsError('3D heat solve requires finite strictly positive temperature')
            residual = self._matrix@temperature.ravel()-rhs.ravel()
            error = float(np.linalg.norm(residual, np.inf)/max(
                np.linalg.norm(rhs.ravel(), np.inf), np.finfo(float).tiny))
            if not math.isfinite(error) or error > 1e-11:
                raise TectonicsError('3D heat linear residual exceeds fixed acceptance tolerance')
            enthalpy = _factored_scale(temperature, (self._cell_capacity,), (), 'final enthalpy')
            source_cells = _factored_scale(sources, (self._volume, duration), (), 'source energy')
            source_energy = _sum(source_cells, 'total source energy')
            outward = {}
            boundary_exchange = []
            for side, (kind, value) in fields.items():
                axis = 'xyz'.index(side[0])
                face_energy = (_factored_scale(temperature[self._faces[side]]-value,
                    (2., self._conductivity, self._areas[axis], duration),
                    (self._spacing[axis],), 'boundary energy') if kind == 'temperature'
                    else _factored_scale(value, (self._areas[axis], duration), (), 'boundary energy'))
                outward[side] = _sum(face_energy, 'total boundary energy')
                boundary_exchange.append(_sum(np.abs(face_energy), 'absolute boundary energy'))
            initial_energy = _sum(old, 'initial total energy')
            final_energy = _sum(enthalpy, 'final total energy')
            change = _sum(enthalpy-old, 'enthalpy change')
            balance = _sum([change, -source_energy, *outward.values()], 'energy balance')
            energy_scale = max(initial_energy, final_energy, abs(source_energy),
                               *(abs(v) for v in outward.values()), np.finfo(float).tiny)
            relative = abs(balance)/energy_scale
            if not math.isfinite(relative) or relative > 1e-11:
                raise TectonicsError('3D heat energy balance exceeds fixed acceptance tolerance')
            # Also expose the increment/flux scale: a large background sensible
            # heat stock must not disguise the accuracy of a small exchange.
            # This explicit storage-roundoff reference is diagnostic only; it
            # is NOT added to or used to relax the fixed acceptance gate above.
            exchange_scale = max(_sum(np.abs(enthalpy-old), 'absolute enthalpy changes'),
                _sum(np.abs(source_cells), 'absolute source energy'),
                _sum(boundary_exchange, 'absolute boundary exchanges'), np.finfo(float).tiny)
            exchange_relative = abs(balance)/exchange_scale
            if not math.isfinite(exchange_relative):
                raise TectonicsError('3D heat exchange residual exceeds finite binary64 range')
            roundoff_allowance = 32.*np.finfo(float).eps*max(initial_energy, final_energy)
            metadata = dict(schema='atlas.regional-heat3d-step.v1', plan_id=self.plan_id,
                plan=self._definition, duration_s=duration, source_id=source_id,
                input_enthalpy_sha256=mechanics3d._digest_array(old),
                source_w_m3_sha256=mechanics3d._digest_array(sources),
                boundaries={side:dict(kind=kind, sha256=mechanics3d._digest_array(value))
                            for side, (kind, value) in fields.items()},
                linear_relative_residual=error, initial_energy_j=initial_energy,
                final_energy_j=final_energy, enthalpy_change_j=change,
                source_energy_j=source_energy, outward_boundary_energy_j=outward,
                energy_balance_error_j=balance, energy_balance_absolute_error_j=abs(balance),
                energy_balance_scale_j=energy_scale, energy_balance_relative_residual=relative,
                energy_exchange_scale_j=exchange_scale,
                energy_exchange_relative_residual=exchange_relative,
                energy_roundoff_allowance_j=roundoff_allowance,
                scientific_acceptance=False, scope='one heat-conduction interval; no advection or phase change')
            result = RegionalMechanicalSnapshot(metadata,
                dict(temperature_k=temperature, enthalpy_j=enthalpy))
            _cancel(cancel)
            self._verify()
            self._stats['advances'] += 1
            return result

    def close(self):
        if getattr(self, '_active', False):
            raise TectonicsError('cannot close an active 3D heat operation')
        if getattr(self, '_closed', True):
            return
        self._closed = True
        self._factor = self._matrix = self._factor_key = self._diffusion = self._indices = None
        self._context = None
        for guard in reversed(self._reservations):
            guard.__exit__(None, None, None)
        self._reservations.clear()

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()
