"""Finite, prescribed bulk magma transfer; not a migration or eruption predictor.

Balanced well-mixed reservoirs and homogeneous finite feeds use one exact
augmented matrix exponential, including integrated edge exports. Variable-mass
mixing uses bounded DOP853 with nonnegative admitted transfer maps. Every
evaluation branches from its supplied initial inventory; step6 owns event history.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import threading
import weakref

import numpy as np
from scipy.integrate import DOP853
from scipy.linalg import expm

from ._validation import TectonicsError, frozen, input_shape, read_array, scalar
from .constitutive import _cancel
from .materials import _name, _json
from .resources import WorkBudget, select_budget
from .stokes_execution import _native_lease

CAP = 128*1024**2
ROUND = 128*np.finfo(float).eps
KINDS = ('source-solid', 'source-melt', 'reservoir', 'intrusion', 'extrusion', 'export')


def _sum(values):
    try: value = math.fsum(float(x) for x in values)
    except (ValueError, OverflowError) as exc:
        raise TectonicsError('magmatic account exceeds finite arithmetic') from exc
    if not math.isfinite(value): raise TectonicsError('nonfinite magmatic account')
    return value


def _identity(record, *arrays):
    h = hashlib.sha256(_json(record))
    for a in arrays:
        h.update(_json((a.shape, a.dtype.str))); h.update(a.tobytes())
    return h.hexdigest()


def _keep(array, owner):
    out = frozen(array)
    lease = owner.reserve(out.nbytes+256, category='magma-retained-array')
    lease.__enter__()
    root = out
    while isinstance(root.base, np.ndarray): root = root.base
    weakref.finalize(root, lease.__exit__, None, None, None)
    return out


def _names(values, label, limit):
    if type(values) is not tuple or not 1 <= len(values) <= limit:
        raise TectonicsError('bounded tuple of '+label+' required')
    for value in values: _name(value, label)
    if values != tuple(sorted(set(values))):
        raise TectonicsError(label+' must be unique and lexically sorted')
    return values


@dataclass(frozen=True, init=False)
class MagmaticInventory:
    node_ids: tuple
    node_kinds: tuple
    component_ids: tuple
    time_s: float
    source_id: str
    enthalpy_source: str
    inventory_id: str
    _components: np.ndarray
    _enthalpy: np.ndarray

    def __init__(self, node_ids, node_kinds, component_ids, component_mass_kg,
                 enthalpy_j, *, source_id, enthalpy_source, time_s=0., budget=None, cancel=None):
        _cancel(cancel)
        nodes = _names(node_ids, 'node IDs', 64)
        components = _names(component_ids, 'component IDs', 64)
        if type(node_kinds) is not tuple or len(node_kinds) != len(nodes) or any(k not in KINDS for k in node_kinds):
            raise TectonicsError('explicit supported kind per node required')
        _name(source_id, 'source'); _name(enthalpy_source, 'enthalpy convention')
        now = scalar(time_s, 'inventory time')
        if (input_shape(component_mass_kg) != (len(nodes), len(components))
                or input_shape(enthalpy_j) != (len(nodes),)):
            raise TectonicsError('component(N,K) and enthalpy(N) shapes required')
        owner = WorkBudget(CAP, parent=select_budget(budget))
        with owner.reserve(64*len(nodes)*(len(components)+2)+8192, category='magma-input'):
            c = read_array(component_mass_kg, 'component mass', nonnegative=True)
            e = read_array(enthalpy_j, 'signed enthalpy')
            mass = np.array([_sum(row) for row in c])
            if np.any((mass == 0) & (e != 0)):
                raise TectonicsError('empty stock cannot contain enthalpy or implicit throughflow')
            record = dict(schema='atlas.magmatic-inventory.v1', nodes=nodes, kinds=node_kinds,
                components=components, source=source_id, enthalpy_source=enthalpy_source, time_s=now)
            values = dict(node_ids=nodes, node_kinds=node_kinds, component_ids=components,
                time_s=now, source_id=source_id, enthalpy_source=enthalpy_source,
                inventory_id=_identity(record, c, e), _components=_keep(c, owner), _enthalpy=_keep(e, owner))
            for key, value in values.items(): object.__setattr__(self, key, value)
        _cancel(cancel)

    @property
    def component_mass_kg(self): return self._components.view()
    @property
    def enthalpy_j(self): return self._enthalpy.view()
    @property
    def mass_kg(self): return frozen([_sum(row) for row in self._components])
    @property
    def nbytes(self): return self._components.nbytes+self._enthalpy.nbytes


class MagmaticExhaustionError(TectonicsError):
    def __init__(self, duration_s, nodes):
        self.exhaustion_duration_s = duration_s
        self.exhausted_node_ids = nodes
        super().__init__('finite magma stock exhausts at '+repr(duration_s)+' s; provide an explicit next event')


@dataclass(frozen=True)
class MagmaticTransferResult:
    remaining: MagmaticInventory
    plan_id: str
    result_id: str
    duration_s: float
    edge_ids: tuple
    _edge_mass: np.ndarray
    _edge_components: np.ndarray
    _edge_enthalpy: np.ndarray
    _heat: np.ndarray
    _metadata: bytes

    @property
    def transferred_mass_kg(self): return self._edge_mass.view()
    @property
    def transferred_component_mass_kg(self): return self._edge_components.view()
    @property
    def transferred_enthalpy_j(self): return self._edge_enthalpy.view()
    @property
    def external_heat_j(self): return self._heat.view()
    def descriptor(self): return json.loads(self._metadata)

    def payload(self, edge_index, source_density_kg_m3, *, budget=None, cancel=None):
        """One cumulative edge parcel, not a new source or permission to spend twice."""
        from .magmatic_emplacement import MagmaticPayload
        if type(edge_index) is not int or not 0 <= edge_index < len(self.edge_ids):
            raise TectonicsError('valid edge index required')
        receiver = self.remaining.node_ids.index(self.edge_ids[edge_index][1])
        if self.remaining.node_kinds[receiver] not in ('intrusion', 'extrusion'):
            raise TectonicsError('only a terminal emplacement transfer is a placement payload')
        return MagmaticPayload(self.remaining.component_ids, self._edge_components[edge_index],
            self._edge_enthalpy[edge_index], source_density_kg_m3,
            source_id=self.result_id, transfer_id=self.result_id+':'+str(edge_index),
            enthalpy_source=self.remaining.enthalpy_source,
            budget=budget, cancel=cancel)


class PreparedMagmaticTransfer:
    """One finite constant-rate segment, with bounded latest-result reuse.

    Rates are supplied kg/s, rows donors/columns receivers. Arbitrary variable-
    mass mixing is admitted only before a singular mixed-reservoir exhaustion.
    Pure finite-feed exhaustion is an exact supported event. No empty node may
    pass material through without a separate prescribed zero-storage closure.
    """
    _BOUND_FIELDS = frozenset(('inventory','rates','heat','mass','net','qout','qin',
        'edges','feed','exact','exhaustion_duration_s','exhausted_node_ids',
        'thermodynamics','context','plan_id','budget','own_context','_heat_scale'))

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False) and name in self._BOUND_FIELDS:
            raise AttributeError('prepared scientific inputs are immutable')
        object.__setattr__(self,name,value)

    def __init__(self, inventory, rates_kg_s, *, source_id, heat_w=None,
                 thermodynamics=None, context=None, budget=None, cancel=None):
        from .reuse import ExecutionContext
        if not isinstance(inventory, MagmaticInventory): raise TectonicsError('MagmaticInventory required')
        if context is not None and (not isinstance(context,ExecutionContext) or context.backend!='scipy'):
            raise TectonicsError('magmatic transfer requires a scipy execution context')
        _name(source_id, 'transfer source'); _cancel(cancel)
        n = len(inventory.node_ids); k = len(inventory.component_ids)
        if input_shape(rates_kg_s) != (n, n): raise TectonicsError('donor-by-receiver rate matrix required')
        self.budget = WorkBudget(CAP, parent=select_budget(budget))
        # 64 nodes,256 edges; work below reserves only realised compact dimensions.
        self._guard = self.budget.reserve(64*n*n+64*n*(k+2)+65536, category='magma-prepared')
        self._guard.__enter__(); self._closed = False; self._active = False
        self._thread = threading.get_ident(); self._latest = None
        self._operator = None; self._operator_time = None; self._operator_guard = None
        self.context = None; self.own_context = context is None
        try:
            rates = read_array(rates_kg_s, 'mass rates', nonnegative=True)
            if rates.shape != (n,n): raise TectonicsError('rate shape changed during capture')
            if np.any(np.diag(rates) != 0): raise TectonicsError('self-transfers are not physical edges')
            edges = tuple(zip(*np.nonzero(rates)))
            if len(edges) > 256: raise TectonicsError('at most256 simultaneous transfer edges')
            qout = np.array([_sum(row) for row in rates])
            qin = np.array([_sum(row) for row in rates.T])
            mass = inventory.mass_kg
            if np.any((qout > 0) & (mass == 0)):
                raise TectonicsError('empty donor/pass-through needs an explicit separate rule')
            for i, kind in enumerate(inventory.node_kinds):
                if qout[i] and kind in ('source-solid', 'intrusion', 'extrusion', 'export'):
                    raise TectonicsError('solid melting or terminal remobilisation requires a separate declared process')
            heat = np.zeros(n) if heat_w is None else read_array(heat_w, 'external heat rate')
            if heat.shape != (n,): raise TectonicsError('one signed heat rate per node')
            if np.any((mass == 0) & (qin == 0) & (heat != 0)):
                raise TectonicsError('cannot heat an empty isolated stock')
            self.inventory = inventory; self.rates = frozen(rates); self.heat = frozen(heat)
            self._heat_scale = float(np.max(abs(heat))) or 1.
            self.mass = frozen(mass); self.net = frozen(qin-qout)
            self.qout = frozen(qout); self.qin = frozen(qin); self.edges = edges
            self.feed = np.frombuffer(((qin == 0) & (qout > 0)).tobytes(), dtype=bool)
            self.exact = bool(np.all((qout == 0) | self.feed | (self.net == 0))
                              and not np.any(self.feed & (heat != 0)))
            event_times = [float(mass[i]/(-self.net[i])) if self.net[i] < 0 else math.inf for i in range(n)]
            event = min(event_times)
            self.exhaustion_duration_s = event if math.isfinite(event) else None
            self.exhausted_node_ids = tuple(inventory.node_ids[i] for i,t in enumerate(event_times) if t == event and math.isfinite(t))
            self.thermodynamics = thermodynamics
            if thermodynamics is not None:
                self._phase_check(inventory, cancel)
            self.context = ExecutionContext('scipy') if context is None else context
            self.context.verify()
            record = dict(schema='atlas.magmatic-transfer.v1', initial=inventory.inventory_id,
                source=source_id, execution=self.context.identity, law='supplied-congruent-bulk-transfer',
                method='augmented-expm' if self.exact else 'nonnegative-admission-DOP853',
                thermodynamics=None if thermodynamics is None else thermodynamics.thermodynamics_id)
            self.plan_id = _identity(record, self.rates, self.heat)
            self._sealed = True
        except BaseException:
            self.close(); raise

    def _phase_check(self, inventory, cancel):
        from .magmatic_thermodynamics import invert_enthalpy
        if inventory.component_ids != self.thermodynamics.component_ids:
            raise TectonicsError('thermodynamic component order does not match transfer')
        if inventory.enthalpy_source != self.thermodynamics.thermodynamics_id:
            raise TectonicsError('inventory enthalpy convention does not match supplied law')
        state = invert_enthalpy(inventory.component_mass_kg, inventory.enthalpy_j,
            self.thermodynamics, budget=self.budget, cancel=cancel)
        for i, kind in enumerate(inventory.node_kinds):
            fraction = state.liquid_fraction[i]
            if kind == 'source-melt' and fraction is not None and fraction != 1.:
                raise TectonicsError('source-melt must be fully liquid under the supplied phase rule')
            if kind == 'source-solid' and fraction is not None and fraction != 0.:
                raise TectonicsError('source-solid must be solid under the supplied phase rule')

    def _coefficients(self, t, *, exact=False):
        n = len(self.mass); e = len(self.edges)
        a = np.zeros((n+e+2, n+e+2))
        mass = self.mass+self.net*t
        if np.any((self.qout > 0) & (mass <= 0)):
            raise TectonicsError('mixed-donor exhaustion is singular; supply a resolved cessation segment')
        for j,(donor, receiver) in enumerate(self.edges):
            rate = self.rates[donor, receiver]
            # A held feed stores its initial extensive inventory, not an
            # order-one fraction. q/M0 keeps the matrix well-scaled regardless
            # of whether a source contains grams or megatonnes.
            coefficient = rate/mass[donor]
            a[receiver, donor] += coefficient
            a[n+j, donor] = coefficient
            if not (exact and self.feed[donor]): a[donor, donor] -= coefficient
        # Two nonnegative source maps, combined with signed scalar energies at
        # evaluation. Putting signed W directly in the exponential matrix loses
        # its Metzler structure and can contaminate structural-zero mass entries.
        a[:n, -2] = np.maximum(self.heat,0)/self._heat_scale
        a[:n, -1] = np.maximum(-self.heat,0)/self._heat_scale
        return a

    def _propagator(self, duration, cancel):
        n = len(self.mass); size = n+len(self.edges)+2
        if self.exact:
            if self._operator_time == duration: return self._operator, 1
            a = self._coefficients(0., exact=True)
            p = expm(a*duration)[:, list(range(n))+[size-2,size-1]]
            if not np.isfinite(p).all() or np.any(p[:, :n] < 0):
                raise TectonicsError('matrix exponential did not preserve nonnegative transfer map')
            if self._operator_guard is not None: self._operator_guard.__exit__(None,None,None)
            self._operator = None; self._operator_time = None; self._operator_guard = None
            guard = self.budget.reserve(p.nbytes+512, category='magma-operator-cache')
            guard.__enter__()
            self._operator = frozen(p); self._operator_time = duration; self._operator_guard = guard
            return self._operator, 1
        if self.exhaustion_duration_s is not None and duration == self.exhaustion_duration_s:
            raise TectonicsError('variable-mass mixed exhaustion needs an explicit resolved endpoint law')
        y0 = np.zeros((size, n+2)); y0[:n,:n] = np.eye(n); y0[-2:,-2:] = np.eye(2)
        calls = 0
        def rhs(t, flat):
            nonlocal calls
            calls += 1; _cancel(cancel)
            if calls > 4096: raise TectonicsError('magmatic integration exceeds bounded derivative work')
            return (self._coefficients(t)@flat.reshape(size,n+2)).ravel()
        # Drive one step at a time: retain only active state, never a growing
        # history of maps. No negative trial result can be published or clipped.
        sol = DOP853(rhs, 0., y0.ravel(), duration, rtol=2e-12, atol=2e-14)
        steps = 0
        while sol.status == 'running':
            if steps >= 256:
                raise TectonicsError('magmatic integration failed its256-interval bound')
            sol.step(); steps += 1
            path = sol.y.reshape(size,n+2)
            if not np.isfinite(path).all() or np.any(path[:, :n] < 0):
                raise TectonicsError('variable-mass integration failed nonnegative transfer-map admission')
        if sol.status != 'finished': raise TectonicsError('magmatic integration failed')
        return path, steps

    def evaluate(self, duration_s, *, cancel=None):
        if self._closed or self._active or threading.get_ident() != self._thread:
            raise TectonicsError('magmatic plan closed, active or wrong driving thread')
        duration = scalar(duration_s, 'duration', nonnegative=True)
        if self.exhaustion_duration_s is not None and duration > self.exhaustion_duration_s:
            raise MagmaticExhaustionError(self.exhaustion_duration_s, self.exhausted_node_ids)
        end = scalar(self.inventory.time_s+duration, 'ending time')
        if duration > 0 and end == self.inventory.time_s: raise TectonicsError('unresolved inventory clock')
        self.context.verify(); _cancel(cancel)
        if self._latest is not None and self._latest.duration_s == duration: return self._latest
        n = len(self.mass); e = len(self.edges); k = len(self.inventory.component_ids); size = n+e+2
        # Matrix exponential workspace or active DOP853 stages; no time history.
        work = (40*size*size+40*size*(n+2)+16*size*(k+1))*8+65536
        self._active = True
        try:
            self._latest = None
            with self.budget.reserve(work, category='magma-transfer-work'), _native_lease():
                initial = np.column_stack((self.inventory.component_mass_kg,self.inventory.enthalpy_j))
                x0 = np.vstack((initial,np.r_[np.zeros(k),self._heat_scale],
                                np.r_[np.zeros(k),-self._heat_scale]))
                if duration == 0:
                    values = np.vstack((initial,np.zeros((e+2,k+1)))); steps = 0
                else:
                    propagator, steps = self._propagator(duration,cancel)
                    values = propagator@x0
                final = values[:n].copy(); edges = values[n:n+e].copy()
                mass = self.mass+self.net*duration
                if self.exact:
                    for i in np.flatnonzero(self.feed):
                        if self.exhaustion_duration_s == duration and self.inventory.node_ids[i] in self.exhausted_node_ids:
                            mass[i] = 0.
                        final[i] = initial[i]*(mass[i]/self.mass[i])
                edge_mass = np.array([self.rates[i,j]*duration for i,j in self.edges])
                heat = self.heat*duration
                if not np.isfinite(final).all() or np.any(final[:,:k] < 0) or np.any(edges[:,:k] < 0):
                    raise TectonicsError('nonfinite or negative extensive transfer')
                residuals = []
                for col in range(k+1):
                    external = _sum(heat) if col == k else 0.
                    residual = _sum((*final[:,col],*-initial[:,col],-external))
                    scale = _sum((*abs(initial[:,col]),*abs(final[:,col]),*abs(edges[:,col]),abs(external)))
                    if abs(residual) > ROUND*scale: raise TectonicsError('magmatic extensive account does not close')
                    residuals.append(residual)
                for row, expected in zip(final[:,:k],mass):
                    if abs(_sum(row)-expected) > ROUND*_sum((*row,abs(expected))):
                        raise TectonicsError('integrated composition does not match exact finite mass')
                for row, expected in zip(edges[:,:k],edge_mass):
                    if abs(_sum(row)-expected) > ROUND*_sum((*row,abs(expected))):
                        raise TectonicsError('edge components do not match prescribed transferred mass')
                remaining = MagmaticInventory(self.inventory.node_ids,self.inventory.node_kinds,
                    self.inventory.component_ids,final[:,:k],final[:,k],source_id=self.plan_id,
                    enthalpy_source=self.inventory.enthalpy_source,time_s=end,budget=self.budget,cancel=cancel)
                if self.thermodynamics is not None: self._phase_check(remaining,cancel)
                edge_ids = tuple((self.inventory.node_ids[i],self.inventory.node_ids[j]) for i,j in self.edges)
                record = dict(plan=self.plan_id,duration_s=duration,accepted_intervals=steps,
                    method='augmented-expm' if self.exact else 'nonnegative-admission-DOP853',
                    account_residuals=residuals,source=self.inventory.inventory_id,
                    exhausted_nodes=self.exhausted_node_ids if duration==self.exhaustion_duration_s else (),
                    heat_owner='external_heat_j only; advected edge enthalpy is not an additional heat source',
                    spending='branch of initial inventory; cumulative history owner required')
                result = MagmaticTransferResult(remaining,self.plan_id,_identity(record,final,edges),duration,
                    edge_ids,_keep(edge_mass,self.budget),_keep(edges[:,:k],self.budget),
                    _keep(edges[:,k],self.budget),_keep(heat,self.budget),_json(record))
                _cancel(cancel); self.context.verify(); self._latest = result
                return result
        finally: self._active = False

    def close(self):
        if self._closed: return
        if self._active or threading.get_ident()!=self._thread:
            raise TectonicsError('close idle magmatic plan on its driving thread')
        self._latest = None; self._operator = None
        if self._operator_guard is not None: self._operator_guard.__exit__(None,None,None)
        if self.own_context and self.context is not None: self.context.close()
        self._guard.__exit__(None,None,None); self._closed = True

    def __enter__(self): return self
    def __exit__(self,*_): self.close()
