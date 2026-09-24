"""Finite rock/alluvium incision on an explicit fixed single-receiver graph.

SPACE-family cover and sharp SI erosion-rate thresholds; m=1/2, n=1.
Backward Euler solves slope, rock lowering and mobile cover together. Released
grains are retained by cell/tag for the W09 sediment consumer, not discarded or
silently called ocean export. No deposition, pore-water or structural adapter.
"""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from numbers import Integral
import threading

import numpy as np

from ._validation import TectonicsError, scalar, snapshot, frozen, input_shape
from .constitutive import _cancel
from .materials import _name, _json
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .storage import ArrayStore
from .spreading import _within_budget

CAP = 128 * 1024**2
LIMIT = 256
EPS = np.finfo(float).eps


def _hash(record, *arrays):
    h = hashlib.sha256(_json(record))
    for a in arrays:
        h.update(str(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


@dataclass(frozen=True)
class ErosionTag:
    tag_id: str
    density_kg_m3: float
    specific_enthalpy_J_kg: float
    formation_time_s: float
    origin_id: str
    enthalpy_reference: str

    def __post_init__(self):
        for name in ('tag_id', 'origin_id', 'enthalpy_reference'):
            _name(getattr(self, name), name)
        for name in ('density_kg_m3', 'specific_enthalpy_J_kg', 'formation_time_s'):
            object.__setattr__(self, name, scalar(getattr(self, name), name,
                positive=name == 'density_kg_m3'))


def cover_rates(H_m, Hstar_m, omega_rock_m_s, omega_sediment_m_s,
                critical_rock_m_s, critical_sediment_m_s, *, wet=True):
    """Instantaneous constitutive control, not a frozen-rate evolution method."""
    H = scalar(H_m, 'alluvium thickness', nonnegative=True)
    Hstar = scalar(Hstar_m, 'roughness', positive=True)
    wr, ws, cr, cs = (scalar(v, name, nonnegative=True) for v, name in zip(
        (omega_rock_m_s, omega_sediment_m_s, critical_rock_m_s, critical_sediment_m_s),
        ('rock power', 'sediment power', 'rock threshold', 'sediment threshold')))
    if type(wet) is not bool:
        raise TectonicsError('wet must be bool')
    if not wet:
        return 0., 0.
    return max(wr-cr, 0.)*math.exp(-H/Hstar), max(ws-cs, 0.)*(-math.expm1(-H/Hstar))


def _local_step(H, relief, length, dt, ar, ass, cr, cs, roughness, solid_fraction):
    """Return integrated rock and bulk-cover removal from one monotone root.

    Eliminate n=1 bedrock lowering algebraically; solve the removed thickness,
    not H_new, to retain small transfers without subtractive cancellation.
    """
    if relief <= 0 or (ar == 0 and ass == 0):
        return 0., 0.
    if H == 0:
        # Closed-form downstream-to-upstream n=1 control, no nonlinear loop.
        r = max(ar*relief/length-cr, 0.)*dt/(1+dt*ar/length)
        return r, 0.
    ar, ass = ar/length, ass/length
    lo, hi = 0., min(H,relief)
    y = 0.
    for _ in range(80):
        h, d = H-y, relief-y
        e = math.exp(-h/roughness)
        cover = -math.expm1(-h/roughness)
        br = max(ar*d-cr,0.)
        denom = 1+dt*ar*e
        r = dt*e*br/denom
        bs = max(ass*(d-r)-cs,0.)
        removed, demanded = solid_fraction*y, dt*bs*cover
        residual = removed-demanded
        if not all(math.isfinite(v) for v in (r,removed,demanded)):
            raise TectonicsError('incision outside finite numerical range')
        if abs(residual) <= 16*EPS*(abs(removed)+abs(demanded)):
            return r, y
        if residual > 0: hi = y
        else: lo = y
        dr = dt*e*(br/roughness-ar*denom)/denom**2 if br > 0 else 0.
        dbs = ass*(-1-dr) if bs > 0 else 0.
        derivative = solid_fraction-dt*(dbs*cover-bs*e/roughness)
        nxt = y-residual/derivative
        y = nxt if lo < nxt < hi else (lo+hi)/2
    raise TectonicsError('implicit incision solve did not converge')


@dataclass(frozen=True, init=False)
class ErosionState:
    """All finite stocks and cumulative releases, with a common immutable identity."""
    rock_mass_kg: np.ndarray
    soil_mass_kg: np.ndarray
    released_rock_kg: np.ndarray
    released_soil_kg: np.ndarray
    initial_mass_kg: np.ndarray
    _record: bytes

    def __init__(self, rock_mass_kg, soil_mass_kg, released_rock_kg,
                 released_soil_kg, initial_mass_kg, *, time_s, accepted_intervals,
                 plan_id, parent_id=None, event_id=None):
        for name, value in zip(('rock_mass_kg', 'soil_mass_kg', 'released_rock_kg',
                'released_soil_kg', 'initial_mass_kg'), (rock_mass_kg, soil_mass_kg,
                released_rock_kg, released_soil_kg, initial_mass_kg)):
            shape = input_shape(value, name)
            if len(shape) != (3 if name == 'rock_mass_kg' else 2) or math.prod(shape) > 32768:
                raise TectonicsError('bounded erosion stock array required')
            object.__setattr__(self, name, snapshot(value, name, nonnegative=True))
        n, layers, tags = self.rock_mass_kg.shape
        if not (1 <= n <= 256 and 1 <= layers <= 32 and 1 <= tags <= 16):
            raise TectonicsError('erosion stock shape bound')
        if any(getattr(self, name).shape != (n, tags) for name in
               ('soil_mass_kg', 'released_rock_kg', 'released_soil_kg', 'initial_mass_kg')):
            raise TectonicsError('erosion account shape mismatch')
        if type(accepted_intervals) is not int or not 0 <= accepted_intervals <= LIMIT:
            raise TectonicsError('cumulative erosion interval limit')
        _name(plan_id, 'erosion plan')
        object.__setattr__(self, '_record', _json(dict(time_s=scalar(time_s, 'time'),
            accepted_intervals=accepted_intervals, plan_id=plan_id,
            parent_id=parent_id, event_id=event_id)))
        self.check_balance()

    def descriptor(self):
        return json.loads(self._record)

    @property
    def time_s(self): return self.descriptor()['time_s']
    @property
    def accepted_intervals(self): return self.descriptor()['accepted_intervals']
    @property
    def state_id(self):
        return _hash(self.descriptor(), *self.arrays().values())

    def arrays(self):
        return {name: getattr(self, name) for name in ('rock_mass_kg', 'soil_mass_kg',
            'released_rock_kg', 'released_soil_kg', 'initial_mass_kg')}

    def check_balance(self):
        for i in range(self.soil_mass_kg.shape[0]):
            for k in range(self.soil_mass_kg.shape[1]):
                values = [-self.initial_mass_kg[i,k], *self.rock_mass_kg[i,:,k],
                          self.soil_mass_kg[i,k], self.released_rock_kg[i,k],
                          self.released_soil_kg[i,k]]
                if abs(math.fsum(values)) > 128*EPS*math.fsum(abs(v) for v in values):
                    raise TectonicsError('per-cell tagged erosion account does not close')


class ErosionExhaustionError(TectonicsError):
    """Exact valid endpoint is available as .state; unspecified substrate refuses."""
    def __init__(self, state, cells):
        self.state, self.cells = state, tuple(cells)
        super().__init__('finite rock exhausted; supply identified substrate before continuing')


class PreparedErosion:
    """Reusable ordered graph and material laws; one cached complete request.

    Rock layers are supplied top first and are nonporous. One homogeneous mobile
    cover layer can contain many provenance cohorts, all obeying one soil law.
    The graph is an explicit frozen operator, not a claim of evolving drainage.
    """
    def __setattr__(self, name, value):
        if not name.startswith('_') and hasattr(self, name):
            raise AttributeError('prepare a new erosion plan for changed inputs')
        object.__setattr__(self, name, value)

    def __init__(self, areas_m2, receivers, receiver_lengths_m, basal_m, tags, *,
                 rock_erodibility, sediment_erodibility, rock_threshold_m_s=0.,
                 sediment_threshold_m_s=0., roughness_m=1., porosity=0.4,
                 frame_id, datum_id, source_id, budget=None, store=None):
        self._closed = self._active = False
        self._owner = threading.get_ident()
        self._context = self._guard = self._latest = None
        self._resource = WorkBudget(CAP, parent=select_budget(budget))
        self._stats = dict(preparations=1, computed_intervals=0, latest_hits=0, restored_states=0)
        self._guard = self._resource.reserve(8*1024**2, category='w09-erosion-prepared-work')
        self._guard.__enter__()
        try:
            shape = input_shape(areas_m2, 'areas')
            if len(shape) != 1 or not 1 <= shape[0] <= 256:
                raise TectonicsError('one area per bounded cell required')
            self._n = shape[0]
            self.areas_m2 = snapshot(areas_m2, 'areas', nonnegative=True)
            self.basal_m = self._vector(basal_m, 'basal heights', signed=True)
            self.receiver_lengths_m = self._vector(receiver_lengths_m, 'receiver lengths')
            if np.any(self.receiver_lengths_m <= 0):
                raise TectonicsError('positive receiver lengths required')
            if not isinstance(receivers, (list, tuple, np.ndarray)) or len(receivers) != self._n:
                raise TectonicsError('one integer receiver per cell required')
            r = []
            for v in receivers:
                if isinstance(v, (bool, np.bool_)) or not isinstance(v, Integral) or not -1 <= int(v) < self._n:
                    raise TectonicsError('receiver indices must be integers in -1..n-1')
                r.append(int(v))
            for i, v in enumerate(r):
                if v == i: r[i] = -1
            if any(r[i] >= 0 for i in np.flatnonzero(self.areas_m2 == 0)):
                raise TectonicsError('zero-area cells must be terminal boundaries')
            self.receivers = tuple(r)
            order, visiting = [], set()
            def visit(i):
                if i in visiting: raise TectonicsError('cyclic receiver graph')
                if i in order: return
                visiting.add(i)
                if r[i] >= 0: visit(r[i])
                visiting.remove(i); order.append(i)
            for i in range(self._n): visit(i)
            self._order = tuple(order)
            if not isinstance(tags, (list, tuple)) or not 1 <= len(tags) <= 16 or any(type(t) is not ErosionTag for t in tags):
                raise TectonicsError('1..16 explicit erosion tags required')
            if len({t.tag_id for t in tags}) != len(tags):
                raise TectonicsError('duplicate material tag')
            if len({t.enthalpy_reference for t in tags}) != 1:
                raise TectonicsError('one common enthalpy reference required')
            self.tags = tuple(tags)
            self._rho = np.array([t.density_kg_m3 for t in tags])
            shape = input_shape(rock_erodibility, 'layer erodibility')
            if len(shape) != 2 or shape[0] != self._n or not 1 <= shape[1] <= 32 or math.prod(shape)*len(tags) > 32768:
                raise TectonicsError('bounded cell-by-layer rock laws required')
            self._layers = shape[1]
            self.rock_erodibility = snapshot(rock_erodibility, 'rock erodibility', nonnegative=True)
            self.rock_threshold_m_s = self._law(rock_threshold_m_s, 'rock threshold')
            self.sediment_erodibility = self._vector(sediment_erodibility, 'sediment erodibility')
            self.sediment_threshold_m_s = self._vector(sediment_threshold_m_s, 'sediment threshold')
            self.roughness_m = self._vector(roughness_m, 'roughness')
            self.porosity = self._vector(porosity, 'porosity')
            if np.any(self.roughness_m <= 0) or np.any(self.porosity >= 1):
                raise TectonicsError('positive roughness and porosity in [0,1) required')
            for key, value in (('frame_id',frame_id), ('datum_id',datum_id), ('source_id',source_id)):
                _name(value,key); setattr(self,key,value)
            if store is not None:
                if not isinstance(store, ArrayStore): raise TectonicsError('ArrayStore required')
                _within_budget(self._resource, store._budget)
            self.store = store
            self._context = ExecutionContext('reference')
            self.execution_id = self._context.identity
            self.plan_id = _hash(dict(schema='atlas.w09-erosion.v1', execution=self.execution_id,
                frame=frame_id, datum=datum_id, source=source_id, receivers=r,
                tags=[asdict(t) for t in tags], scheme='implicit-cover-and-slope-n1'),
                self.areas_m2, self.basal_m, self.receiver_lengths_m, self.rock_erodibility,
                self.rock_threshold_m_s, self.sediment_erodibility,
                self.sediment_threshold_m_s, self.roughness_m, self.porosity)
        except BaseException:
            self.close(); raise

    def _vector(self, value, name, signed=False):
        shape = input_shape(value, name)
        if shape == ():
            return frozen(np.full(self._n, scalar(value, name, nonnegative=not signed)))
        if shape != (self._n,): raise TectonicsError(name+': one value per cell required')
        return snapshot(value, name, nonnegative=not signed)

    def _law(self, value, name):
        if input_shape(value, name) == ():
            return frozen(np.full((self._n,self._layers),scalar(value,name,nonnegative=True)))
        a = snapshot(value,name,nonnegative=True)
        if a.shape != (self._n,self._layers): raise TectonicsError(name+': cell/layer shape')
        return a

    def _check(self, cancel=None):
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('erosion plan closed or wrong thread')
        _cancel(cancel); self._context.verify()

    @contextmanager
    def _operation(self, cancel=None):
        self._check(cancel)
        if self._active: raise TectonicsError('reentrant erosion operation')
        self._active = True
        try:
            yield
            self._check(cancel)
        finally:
            self._active = False

    def _validate(self, state):
        if type(state) is not ErosionState or state.descriptor()['plan_id'] != self.plan_id:
            raise TectonicsError('wrong erosion state plan/source')
        if state.rock_mass_kg.shape != (self._n,self._layers,len(self.tags)):
            raise TectonicsError('erosion state shape mismatch')
        if any(np.any(a[self.areas_m2 == 0]) for a in state.arrays().values()):
            raise TectonicsError('mass cannot be placed on zero-area boundary')
        state.check_balance()
        # Enthalpy is a signed, common-reference cohort quantity. Its products
        # must also be representable even if the grain-mass account is finite.
        for k,tag in enumerate(self.tags):
            heat=tag.specific_enthalpy_J_kg
            for i in range(self._n):
                terms=[-float(state.initial_mass_kg[i,k])*heat,
                       *(float(v)*heat for v in state.rock_mass_kg[i,:,k]),
                       float(state.soil_mass_kg[i,k])*heat,
                       float(state.released_rock_kg[i,k])*heat,
                       float(state.released_soil_kg[i,k])*heat]
                if not all(math.isfinite(v) for v in terms):
                    raise TectonicsError('erosion enthalpy outside finite range')
                scale=math.fsum(abs(v) for v in terms)
                if abs(math.fsum(terms)) > 128*EPS*scale:
                    raise TectonicsError('erosion signed enthalpy account does not close')

    def initialise(self, rock_mass_kg, soil_mass_kg=None, *, time_s=0.):
        with self._operation():
            if input_shape(rock_mass_kg,'rock mass') != (self._n,self._layers,len(self.tags)):
                raise TectonicsError('rock mass cell/layer/tag shape mismatch')
            rock = snapshot(rock_mass_kg,'rock mass',nonnegative=True)
            soil = np.zeros((self._n,len(self.tags))) if soil_mass_kg is None else snapshot(soil_mass_kg,'soil mass',nonnegative=True)
            if soil.shape != (self._n,len(self.tags)): raise TectonicsError('soil cell/tag shape mismatch')
            initial = rock.sum(axis=1)+soil
            out = ErosionState(rock,soil,np.zeros_like(soil),np.zeros_like(soil),initial,
                time_s=time_s,accepted_intervals=0,plan_id=self.plan_id)
            self._validate(out)
            if any(t.formation_time_s > out.time_s for t in self.tags):
                raise TectonicsError('material formation cannot follow state time')
            self._geometry(rock,soil)
            return out

    def _geometry(self, rock, soil):
        volume = np.sum(rock/self._rho,axis=(1,2))
        soil_volume = np.sum(soil/self._rho,axis=1)
        area = np.where(self.areas_m2 > 0,self.areas_m2,1.)
        H = soil_volume/(area*(1-self.porosity))
        z = self.basal_m+volume/area+H
        if not np.isfinite(z).all(): raise TectonicsError('surface outside binary64 range')
        for i,j in enumerate(self.receivers):
            if j >= 0 and z[i] < z[j]: raise TectonicsError('receiver is uphill; rebuild routing')
        return z,H

    def heights(self, state):
        with self._operation():
            self._validate(state)
            return frozen(self._geometry(state.rock_mass_kg,state.soil_mass_kg)[0])

    def released_enthalpy_J(self, state):
        with self._operation():
            self._validate(state)
            return frozen((state.released_rock_kg+state.released_soil_kg)*
                          np.array([t.specific_enthalpy_J_kg for t in self.tags]))

    def _trial(self, rock, soil, dt, qroot, inundated, cancel):
        z,H = self._geometry(rock,soil)
        initial_z = z.copy()
        dr, ds = np.zeros(self._n), np.zeros(self._n)
        active = np.full(self._n,-1,dtype=int)
        avail = np.zeros(self._n)
        for i in self._order:
            _cancel(cancel)
            j = self.receivers[i]
            if j < 0 or qroot[i] == 0 or inundated[i] or self.areas_m2[i] == 0: continue
            candidates = np.flatnonzero(np.any(rock[i] > 0,axis=1))
            if candidates.size:
                k = active[i] = candidates[0]
                avail[i] = math.fsum(rock[i,k]/self._rho)/self.areas_m2[i]
            else:
                # The last supplied law is used only to detect attempted erosion
                # of absent rock; no zero-rate substrate is silently invented.
                k = self._layers-1
            dr[i], removed_bulk = _local_step(H[i],max(initial_z[i]-z[j],0.),
                self.receiver_lengths_m[i],dt,self.rock_erodibility[i,k]*qroot[i],
                self.sediment_erodibility[i]*qroot[i],self.rock_threshold_m_s[i,k],
                self.sediment_threshold_m_s[i],self.roughness_m[i],1-self.porosity[i])
            ds[i] = removed_bulk*(1-self.porosity[i])
            z[i] -= dr[i]+removed_bulk
        return dr,ds,active,avail

    def _new(self, previous, rock, soil, rr, rs, elapsed, count, event):
        return ErosionState(rock,soil,rr,rs,previous.initial_mass_kg,
            time_s=previous.time_s+elapsed,accepted_intervals=previous.accepted_intervals+count,
            plan_id=self.plan_id,parent_id=previous.state_id,event_id=event)

    def prescribed_release(self, state, cell, rate_kg_s, duration_s, *, source_id, cancel=None):
        """Finite ordered extraction adapter/control, not an erosion calibration.

        Debits identified rock at an externally prescribed constant mass rate.
        Full depletion returns its valid endpoint in ErosionExhaustionError.
        """
        with self._operation(cancel):
            self._validate(state); _name(source_id,'extraction source')
            if type(cell) is not int or not 0 <= cell < self._n or self.areas_m2[cell] == 0:
                raise TectonicsError('positive-area integer extraction cell required')
            rate=scalar(rate_kg_s,'extraction rate',positive=True)
            duration=scalar(duration_s,'extraction duration',positive=True)
            if not math.isfinite(state.time_s+duration) or state.time_s+duration == state.time_s:
                raise TectonicsError('extraction endpoint not representable')
            rock,rr=state.rock_mass_kg.copy(),state.released_rock_kg.copy()
            elapsed=0.; count=0
            for layer in range(self._layers):
                mass=math.fsum(rock[cell,layer])
                if mass == 0: continue
                if state.accepted_intervals+count >= LIMIT:
                    raise TectonicsError('cumulative erosion interval limit')
                dt=min(duration-elapsed,mass/rate)
                if elapsed+dt == elapsed: raise TectonicsError('extraction event not representable')
                amount=mass if dt == mass/rate else rate*dt
                moved=rock[cell,layer]*(amount/mass)
                rock[cell,layer]-=moved; rr[cell]+=moved
                elapsed+=dt; count+=1
                if elapsed >= duration: break
            key=_hash(dict(parent=state.state_id,cell=cell,rate=rate,duration=duration,source=source_id))
            out=self._new(state,rock,state.soil_mass_kg,rr,state.released_soil_kg,elapsed,count,key)
            self._check(cancel)
            if elapsed < duration: raise ErosionExhaustionError(out,[cell])
            return out

    def advance(self, state, duration_s, *, discharge_m3_s, inundated=None,
                forcing_id, partitions=1, cancel=None):
        with self._operation(cancel):
            self._validate(state); _name(forcing_id,'forcing provenance')
            duration = scalar(duration_s,'erosion duration',positive=True)
            if not math.isfinite(state.time_s+duration) or state.time_s+duration == state.time_s:
                raise TectonicsError('erosion endpoint not representable')
            if type(partitions) is not int or not 1 <= partitions <= LIMIT:
                raise TectonicsError('bounded integer partitions required')
            q = self._vector(discharge_m3_s,'physical discharge')
            if inundated is None: wet = np.zeros(self._n,dtype=bool)
            else:
                if not isinstance(inundated,(list,tuple,np.ndarray)) or len(inundated) != self._n or any(type(v) not in (bool,np.bool_) for v in inundated):
                    raise TectonicsError('explicit boolean inundation mask required')
                wet = np.array(inundated,dtype=bool,copy=True)
            key = _hash(dict(parent=state.state_id,duration=duration,forcing=forcing_id,
                inundated=wet.tolist(),partitions=partitions),q)
            if self._latest is not None and self._latest[0] == key:
                self._stats['latest_hits'] += 1
                return self._latest[1]
            rock,soil,rr,rs = (a.copy() for a in (state.rock_mass_kg,state.soil_mass_kg,
                state.released_rock_kg,state.released_soil_kg))
            qroot = np.sqrt(q); elapsed = 0.; count = 0
            for partition in range(partitions):
                target = duration*(partition+1)/partitions
                while elapsed < target:
                    _cancel(cancel)
                    if state.accepted_intervals+count >= LIMIT:
                        raise TectonicsError('cumulative erosion interval limit')
                    dt = target-elapsed
                    trial = self._trial(rock,soil,dt,qroot,wet,cancel)
                    dr,ds,active,avail = trial
                    absent = np.flatnonzero((active < 0)&(dr > 0))
                    if absent.size:
                        raise ErosionExhaustionError(self._new(state,rock,soil,rr,rs,elapsed,count,key),absent)
                    if np.any(dr > avail):
                        # First layer event for the same implicit global operator.
                        # Trial states are never committed or counted as time steps.
                        lo,hi = 0.,dt
                        for _ in range(64):
                            mid = (lo+hi)/2
                            candidate = self._trial(rock,soil,mid,qroot,wet,cancel)
                            if np.any(candidate[0] > candidate[3]): hi = mid
                            else: lo = mid; trial = candidate
                            if hi-lo <= 8*EPS*max(hi,np.finfo(float).tiny): break
                        dt = lo
                        dr,ds,active,avail = trial
                    if dt <= 0 or elapsed+dt == elapsed:
                        raise TectonicsError('finite layer event not representable')
                    for i in range(self._n):
                        if active[i] >= 0 and dr[i] > 0:
                            k = active[i]
                            fraction = dr[i]/avail[i]
                            # Exact event equality in binary64: release remaining
                            # represented stock, not an unbooked negative clipping.
                            if 0 <= 1-fraction <= 32*EPS: fraction = 1.
                            moved = rock[i,k]*fraction
                            rock[i,k] -= moved; rr[i] += moved
                        if ds[i] > 0:
                            available = math.fsum(soil[i]/self._rho)
                            fraction = ds[i]*self.areas_m2[i]/available
                            if not 0 <= fraction <= 1:
                                raise TectonicsError('implicit sediment removal exceeds finite supply')
                            moved = soil[i]*fraction
                            soil[i] -= moved; rs[i] += moved
                    elapsed += dt; count += 1
            out = self._new(state,rock,soil,rr,rs,duration,count,key)
            self._validate(out); self._geometry(rock,soil); self._check(cancel)
            self._stats['computed_intervals'] += count
            self._latest = (key,out)
            return out

    def checkpoint(self, state, *, cancel=None):
        with self._operation(cancel):
            self._validate(state)
            if self.store is None: raise TectonicsError('checkpoint requires ArrayStore')
            key = _hash(dict(plan=self.plan_id,state=state.state_id))
            self.store.put(key,state.arrays(),dict(schema='atlas.w09-erosion-checkpoint.v1',
                plan=self.plan_id,state_id=state.state_id,state=state.descriptor()),
                publication_check=lambda:self._check(cancel))
            return key

    def restore(self, key, *, cancel=None):
        with self._operation(cancel):
            if self.store is None: raise TectonicsError('restore requires ArrayStore')
            meta = self.store.metadata(key)
            if not isinstance(meta,dict) or meta.get('schema') != 'atlas.w09-erosion-checkpoint.v1' or meta.get('plan') != self.plan_id:
                raise TectonicsError('missing or incompatible erosion checkpoint')
            arrays = self.store.get(key,budget=self._resource)
            if arrays is None: raise TectonicsError('missing erosion arrays')
            out = ErosionState(**arrays,**meta['state'])
            self._validate(out)
            if out.state_id != meta['state_id'] or key != _hash(dict(plan=self.plan_id,state=out.state_id)):
                raise TectonicsError('erosion checkpoint identity mismatch')
            self._stats['restored_states'] += 1
            return out

    def statistics(self): return dict(self._stats,budget=self._resource.statistics())

    def close(self):
        if not self._closed:
            self._closed=True; self._latest=None
            try:
                if self._context is not None: self._context.close()
            finally:
                if self._guard is not None:
                    self._guard.__exit__(None,None,None); self._guard=None

    def __enter__(self): self._check(); return self
    def __exit__(self,*_): self.close()
