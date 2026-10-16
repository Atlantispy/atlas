"""One conservative conduction solve for a box and finite adjacent cells.

Each declared exterior cell is an orthogonal prism over one complete box face
cell. Its other faces are insulated. This is a finite-volume thermal boundary,
not a prescribed-temperature reservoir or a claim of curved-cell support.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from ._validation import TectonicsError, scalar
from .regional_heat3d import PreparedRegionalHeat3D, SIDES, _field, _cancel, _sum
from .regional_execution import RegionalMechanicalSnapshot
from . import regional_execution3d as X
from .resources import MemoryLimitError
from .stokes_execution import _native_lease

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExteriorThermalCell:
    """Actual adjacent full-face prism, named by its material inventory owner."""
    owner_id: str
    side: str
    face_index: tuple
    depth_m: float
    heat_capacity_j_m3_k: float
    conductivity_w_m_k: float

    def __post_init__(self):
        X._name(self.owner_id, 'exterior thermal owner')
        if type(self.side) is not str or self.side not in SIDES:
            raise TectonicsError('an actual box side is required')
        if (type(self.face_index) is not tuple or len(self.face_index) != 2 or
                any(type(i) is not int or i < 0 for i in self.face_index)):
            raise TectonicsError('two nonnegative integer face-cell indices required')
        for key in ('depth_m', 'heat_capacity_j_m3_k', 'conductivity_w_m_k'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))

    def record(self):
        return dict(owner_id=self.owner_id, side=self.side, face_index=list(self.face_index),
                    depth_m=self.depth_m, heat_capacity_j_m3_k=self.heat_capacity_j_m3_k,
                    conductivity_w_m_k=self.conductivity_w_m_k)


def _exact(value):
    q = value if type(value) is Q else Q(float(value))
    return [hex(q.numerator), hex(q.denominator)]


def _positive_float(value):
    """One final binary64 projection; intermediate physical products stay exact."""
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError('unrepresentable finite exterior capacity or conductance') from exc
    if not math.isfinite(result) or result <= 0:
        raise TectonicsError('unrepresentable finite exterior capacity or conductance')
    return result


class PreparedFiniteExteriorHeat3D:
    """Reuse the box interior operator, adding paired implicit interface edges.

    Fixed positive capacities and half-cell series resistances define the
    discretisation before a run. No incoming temperature is imposed. The same
    interface Joules leave one owner and enter the other, with binary storage
    residuals recorded separately. Ordinary boundary conditions apply only to
    unconnected faces: connected face entries must explicitly be zero flux.
    The caller owns the box plan and the actual exterior material inventories.
    """
    def __init__(self, interior, cells, *, source_id, budget):
        self._guard = None
        self._factor = self._matrix = self._key = None
        if type(interior) is not PreparedRegionalHeat3D or budget is not interior._resource:
            raise TectonicsError('actual heat plan on the same resource budget required')
        X._name(source_id, 'finite exterior geometry/source')
        if type(cells) is not tuple or not cells or any(type(c) is not ExteriorThermalCell for c in cells):
            raise TectonicsError('nonempty typed adjacent exterior cells required')
        if len(cells) > sum(2*math.prod(interior._cells[j] for j in range(3) if j != i) for i in range(3)):
            raise TectonicsError('at most one exterior cell per physical boundary face cell')
        self._inner, self._cells, self._budget = interior, cells, budget
        n = interior._count+len(cells)
        self._factor_allowance = 24*n*n+1024*n
        self._guard = budget.reserve(2*1024**2+4096*n+self._factor_allowance,
                                     category='finite-exterior-heat-plan')
        self._guard.__enter__()
        try:
            interior._verify()
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
                raise TectonicsError('finite exterior heat source changed since import')
            self._tokens = X._local_tokens(sys.modules[__name__])
            indices, conductances, capacities, used = [], [], [], set()
            for c in cells:
                key = c.side, c.face_index
                if key in used:
                    raise TectonicsError('overlapping exterior thermal cells')
                used.add(key)
                axis = 'xyz'.index(c.side[0])
                tangents = [j for j in range(3) if j != axis]
                if any(k >= interior._cells[j] for k, j in zip(c.face_index, tangents)):
                    raise TectonicsError('exterior heat cell lies outside its actual face')
                index = [0, 0, 0]
                index[axis] = 0 if c.side[1] == '0' else interior._cells[axis]-1
                for k, j in zip(c.face_index, tangents):
                    index[j] = k
                indices.append(int(interior._indices[tuple(index)]))
                # Integrate the two orthogonal half-cell resistances in series.
                area = interior._areas[axis]
                resistance = (Q(interior._spacing[axis])/(2*Q(interior._conductivity))+
                              Q(c.depth_m)/(2*Q(c.conductivity_w_m_k)))
                conductances.append(_positive_float(Q(area)/resistance))
                capacities.append(_positive_float(Q(area)*Q(c.depth_m)*Q(c.heat_capacity_j_m3_k)))
            self._ports = np.asarray(indices, dtype=np.int64)
            self._conductance = np.asarray(conductances)
            self._capacity = np.r_[np.full(interior._count, interior._cell_capacity), capacities]
            if (not np.isfinite(self._capacity).all() or not np.isfinite(self._conductance).all() or
                    np.any(self._capacity <= 0) or np.any(self._conductance <= 0)):
                raise TectonicsError('unrepresentable finite exterior capacity or conductance')
            with _native_lease(), np.errstate(over='raise', invalid='raise'):
                try:
                    L = sparse.block_diag((interior._diffusion*interior._cell_capacity,
                                           sparse.csc_matrix((len(cells), len(cells)))), format='csc')
                    outside = np.arange(interior._count, n)
                    rows = np.r_[self._ports, outside, self._ports, outside]
                    cols = np.r_[self._ports, outside, outside, self._ports]
                    vals = np.r_[self._conductance, self._conductance, -self._conductance, -self._conductance]
                    self._laplacian = L+sparse.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsc()
                except FloatingPointError as exc:
                    raise TectonicsError('unrepresentable finite exterior heat graph') from exc
            self._definition = dict(schema='atlas.finite-exterior-heat-plan.v1',
                interior=interior.descriptor(), exterior_cells=[c.record() for c in cells],
                source_id=source_id, conductance_w_k=self._conductance.tolist(),
                capacities_j_k=self._capacity.tolist(),
                method='one backward-Euler finite-volume graph; paired series-resistance interfaces',
                linear_representation='constant reference plus temperature deviations; full sensible enthalpy stored',
                exterior_other_faces='insulated', geometry='full orthogonal adjacent prisms; no curved cells',
                linear_relative_tolerance=1e-11, energy_relative_tolerance=1e-11,
                scope='conduction only; caller carries actual material state and its finite exterior enthalpy')
            self.plan_id = X._hash(self._definition)
            self._stats = dict(advances=0, factorizations=0, factor_reuses=0)
        except BaseException:
            self.close()
            raise

    def _verify(self):
        if self._guard is None:
            raise TectonicsError('finite exterior heat plan is closed')
        self._inner._verify()
        if X._local_tokens(sys.modules[__name__]) != self._tokens:
            raise TectonicsError('loaded finite exterior heat implementation changed')

    @property
    def interior(self):
        """The actual shared interior operator; the wrapper never owns its life."""
        self._verify()
        return self._inner

    def descriptor(self):
        self._verify()
        return json.loads(X._json(self._definition))

    def statistics(self):
        self._verify()
        return dict(self._stats)

    def advance(self, enthalpy_j, exterior_enthalpy_j, duration_s, boundaries, source_w_m3,
                *, source_id, exterior_state_id, cancel=None):
        """Return both successor enthalpies from one solve, without publishing."""
        self._verify()
        X._name(source_id, 'heat source'); X._name(exterior_state_id, 'actual exterior state')
        h = self._inner
        # A sum/difference of finite binary64 values has denominator at most
        # 2**1074 and numerator at most 2099+ceil(log2(term_count)) bits.
        # Charge integer objects, canonical hex, JSON and immutable snapshot
        # copies separately from retained plan arrays/factor workspace.
        terms = 8*(h._count+len(self._cells))+1
        exact_bytes = 256+(2099+terms.bit_length()+1075+3)//4
        audit_bytes = 65536+512*(h._count+len(self._cells))+8*(len(self._cells)+4)*exact_bytes
        with h._operation(cancel), self._budget.reserve(audit_bytes, category='finite-exterior-heat-audit'):
            dt = scalar(duration_s, 'heat duration', positive=True)
            old = _field(enthalpy_j, h._cells, 'interior enthalpy', positive=True)
            exterior = _field(exterior_enthalpy_j, (len(self._cells),), 'finite exterior enthalpy', positive=True)
            source = _field(source_w_m3, h._cells, 'heat source', scalar_ok=True)
            fields = h._boundaries(boundaries)
            for c in self._cells:
                kind, value = fields[c.side]
                if kind != 'flux' or value[c.face_index] != 0:
                    raise TectonicsError('connected face cannot also have prescribed temperature or heat flux')
            energy = np.r_[old.ravel(), exterior]
            reference = float(energy[0]/self._capacity[0])
            # L*constant=0 exactly in the mathematical FV graph. Solve for a
            # temperature deviation so cancelling its assembled row sums cannot
            # turn uniform equilibrium into a heat transfer.
            initial_deviation_energy = energy-self._capacity*reference
            rhs = initial_deviation_energy.copy()
            source_energy = dt*h._volume*source.ravel()
            rhs[:h._count] += source_energy
            boundary_diag = np.zeros(len(energy))
            for side, (kind, value) in fields.items():
                axis, view = 'xyz'.index(side[0]), h._faces[side]
                ix = h._indices[view].ravel()
                if kind == 'temperature':
                    g = 2*h._conductivity*h._areas[axis]/h._spacing[axis]
                    boundary_diag[ix] += g
                    rhs[ix] += dt*g*(value.ravel()-reference)
                else:
                    rhs[ix] -= dt*h._areas[axis]*value.ravel()
            key = (dt, tuple(fields[s][0] for s in SIDES))
            if key != self._key:
                self._factor = self._matrix = self._key = None
                matrix = dt*self._laplacian+sparse.diags(self._capacity+dt*boundary_diag, format='csc')
                if not np.isfinite(matrix.data).all() or not np.isfinite(rhs).all():
                    raise TectonicsError('nonfinite coupled heat equation')
                _cancel(cancel)
                try:
                    factor = splu(matrix, permc_spec='COLAMD')
                except RuntimeError as exc:
                    raise TectonicsError('finite exterior heat factorisation failed') from exc
                if 12*factor.nnz+8*(len(energy)+1) > self._factor_allowance:
                    raise MemoryLimitError('finite exterior heat factor exceeded admitted allowance')
                _cancel(cancel)
                self._matrix, self._factor, self._key = matrix, factor, key
                self._stats['factorizations'] += 1
            else:
                self._stats['factor_reuses'] += 1
            _cancel(cancel)
            deviation = self._factor.solve(rhs)
            _cancel(cancel)
            temperature = reference+deviation
            if not np.isfinite(temperature).all() or np.any(temperature <= 0):
                raise TectonicsError('finite exterior heat requires positive finite temperature')
            residual = self._matrix@deviation-rhs
            relative = np.linalg.norm(residual, np.inf)/max(np.linalg.norm(rhs, np.inf), np.finfo(float).tiny)
            if not math.isfinite(relative) or relative > 1e-11:
                raise TectonicsError('finite exterior heat linear residual exceeds existing heat tolerance')
            new = energy+(self._capacity*deviation-initial_deviation_energy)
            if not np.isfinite(new).all() or np.any(new <= 0):
                raise TectonicsError('finite exterior heat requires positive finite stored enthalpy')
            interface = dt*self._conductance*(deviation[self._ports]-deviation[h._count:])
            boundary_energy = {}
            for side, (kind, value) in fields.items():
                axis, view = 'xyz'.index(side[0]), h._faces[side]
                delta = (reference-value)+deviation[:h._count].reshape(h._cells)[view]
                boundary_energy[side] = dt*h._areas[axis]*(
                    2*h._conductivity/h._spacing[axis]*delta if kind == 'temperature' else value)
            external = _sum(np.concatenate([a.ravel() for a in boundary_energy.values()]), 'boundary energy')
            change = _sum(new-energy, 'stored energy change')
            source_total = _sum(source_energy, 'source energy')
            balance = _sum((change, -source_total, external), 'heat balance')
            scale = max(_sum(energy, 'initial energy'), _sum(new, 'final energy'), abs(external), abs(source_total),
                        np.finfo(float).tiny)
            if abs(balance)/scale > 1e-11:
                raise TectonicsError('finite exterior heat energy residual exceeds existing heat tolerance')
            # Equal/opposite interface transfers are the SAME binary64 amount;
            # any final stored-energy residual is visible, not repaired away.
            exterior_roundoff = [Q(float(b))-Q(float(a))-Q(float(q))
                                  for a, b, q in zip(exterior, new[h._count:], interface)]
            exact_change = sum((Q(float(b))-Q(float(a)) for a, b in zip(energy, new)), Q(0))
            exact_source = sum(map(lambda v: Q(float(v)), source_energy), Q(0))
            exact_boundary = sum((Q(float(v)) for a in boundary_energy.values() for v in a.flat), Q(0))
            exact_interface = sum((Q(float(v)) for v in interface), Q(0))
            interior_change = sum((Q(float(b))-Q(float(a)) for a, b in zip(old.flat, new[:h._count])), Q(0))
            interior_roundoff = interior_change-exact_source+exact_boundary+exact_interface
            meta = dict(schema='atlas.finite-exterior-heat-step.v1', plan_id=self.plan_id,
                plan=self._definition, duration_s=dt, source_id=source_id, exterior_state_id=exterior_state_id,
                input_enthalpy_sha256=X._digest_array(old), input_exterior_enthalpy_sha256=X._digest_array(exterior),
                source_w_m3_sha256=X._digest_array(source),
                boundaries={s: dict(kind=k, sha256=X._digest_array(v)) for s, (k, v) in fields.items()},
                linear_relative_residual=float(relative), energy_balance_relative_residual=abs(balance)/scale,
                energy_balance_error_j=balance, exact_storage_balance_j=_exact(exact_change-exact_source+exact_boundary),
                interior_storage_residual_j=_exact(interior_roundoff),
                exterior_storage_residual_j=[_exact(q) for q in exterior_roundoff],
                source_energy_j=source_total, declared_audit_work_bytes=audit_bytes,
                outward_boundary_energy_j={s: _sum(a, 'side boundary energy') for s, a in boundary_energy.items()},
                temperature_reference_k=reference,
                storage_rule='old enthalpy plus solved deviation change; storage residual is explicit, not repaired',
                interface_rule='positive out of interior; equal opposite is credited to named finite exterior cell',
                no_new_heat=True, no_publication=True)
            arrays = dict(temperature_k=temperature[:h._count].reshape(h._cells),
                enthalpy_j=new[:h._count].reshape(h._cells), exterior_temperature_k=temperature[h._count:],
                exterior_enthalpy_j=new[h._count:], interface_outward_energy_j=interface,
                interface_interior_change_j=-interface, interface_exterior_credit_j=interface.copy())
            _cancel(cancel)
            result = RegionalMechanicalSnapshot(meta, arrays)
        self._verify()
        self._stats['advances'] += 1
        return result

    def close(self):
        if getattr(getattr(self, '_inner', None), '_active', False):
            raise TectonicsError('cannot close finite exterior heat during an active heat operation')
        if self._guard is not None:
            self._factor = self._matrix = self._laplacian = None
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
