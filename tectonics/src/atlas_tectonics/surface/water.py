"""Finite water on a prepared drainage graph; ideal outlets, not flood hydraulics.

Piecewise-constant forcing is integrated to bed/sill/drying events. Physical
volumes, routing geometry and infiltrated/evaporated/exported accounts are distinct.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
import threading
from typing import TYPE_CHECKING, cast

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar, frozen, input_shape, snapshot
from atlas_tectonics._validation import _check_owner_thread
from atlas_tectonics._validation import within_budget
from atlas_tectonics.materials.materials import _name, _json
from atlas_tectonics.integration.resources import WorkBudget, select_budget
from atlas_tectonics.integration.resources import _budget_statistics
from atlas_tectonics.integration.resources import _operation as _prepared_operation
from atlas_tectonics.integration.resources import check_event_or_callable
from atlas_tectonics.integration.resources import json_sha256
from atlas_tectonics.integration.reuse import ExecutionContext, content_record
from atlas_tectonics.surface.drainage import prepare_drainage
from atlas_tectonics.surface.erosion import LIMIT

if TYPE_CHECKING:
    from atlas_tectonics.codecs.storage import ArrayStore

CAP = 128 * 1024**2
EPS = np.finfo(float).eps


def _sum(values):
    return math.fsum(float(v) for v in values)


def _tol(*values):
    return 32*EPS*max(1., *(abs(float(v)) for v in values))


def _balance(initial, supplied, water, subsurface, evaporated, exported):
    pass


@dataclass(frozen=True, init=False)
class WaterState:
    """Immutable complete water account; no hidden mutable model cursor."""
    water_m3: np.ndarray
    time_s: float
    subsurface_m3: float
    evaporated_m3: float
    exported_m3: float
    supplied_m3: float
    initial_total_m3: float
    accepted_intervals: int
    geometry_id: str
    execution_id: str
    _record: bytes

    def __init__(self, water_m3, *, time_s, subsurface_m3, evaporated_m3,
                 exported_m3, supplied_m3, initial_total_m3, accepted_intervals,
                 geometry_id, execution_id, parent_id=None, event_id=None):
        w = snapshot(water_m3, 'water volume', nonnegative=True)
        vals = dict(time_s=scalar(time_s, 'water time'),
                    subsurface_m3=scalar(subsurface_m3, 'subsurface water', nonnegative=True),
                    evaporated_m3=scalar(evaporated_m3, 'evaporated water', nonnegative=True),
                    exported_m3=scalar(exported_m3, 'exported water', nonnegative=True),
                    supplied_m3=scalar(supplied_m3, 'supplied water', nonnegative=True),
                    initial_total_m3=scalar(initial_total_m3, 'initial total water', nonnegative=True),
                    accepted_intervals=accepted_intervals, geometry_id=geometry_id,
                    execution_id=execution_id, parent_id=parent_id, event_id=event_id)
        for key in ('geometry_id', 'execution_id'):
            _name(vals[key], key)
        _balance(vals['initial_total_m3'], vals['supplied_m3'], _sum(w),
                 vals['subsurface_m3'], vals['evaporated_m3'], vals['exported_m3'])
        for key, value in vals.items():
            if key not in ('parent_id', 'event_id'):
                object.__setattr__(self, key, value)
        object.__setattr__(self, 'water_m3', w)
        object.__setattr__(self, '_record', _json(vals))

    def descriptor(self):
        return json.loads(self._record)

    @property
    def state_id(self):
        return hashlib.sha256(_json(content_record(self.descriptor())) + self.water_m3.tobytes()).hexdigest()


class PreparedWater:
    """One immutable geometry and at most one result-cache entry, shared budget.

    Methods return complete candidates: cancellation/failure never mutate an
    accepted input. Persistence is explicit through the existing ArrayStore.
    """
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, bed_m, areas_m2, links, link_lengths_m, outlet_nodes, *,
                 frame_id, datum_id, source_id, budget=None, store=None):
        self._closed = self._active = False
        self._owner = threading.get_ident()
        self._context = self._guard = None
        self._latest = None
        self._hypsometry = OrderedDict()
        self._resource = WorkBudget(CAP, parent=select_budget(budget))
        if store is not None:
            within_budget(self._resource, store._budget, 'call budget must descend from the prepared run budget')
        self.store = store
        self._stats = dict(geometry_preparations=1, computed_intervals=0,
                           latest_hits=0, restored_states=0)
        # Bounded Python graph metadata, context, output and event scratch admitted
        # before construction; not an OS RSS guarantee.
        self._guard = self._resource.reserve(8*1024**2, category='w09-prepared-and-event-work')
        self._guard.__enter__()
        try:
            self.geometry = prepare_drainage(bed_m, areas_m2, links, link_lengths_m,
                outlet_nodes, frame_id=frame_id, datum_id=datum_id,
                source_id=source_id, budget=self._resource)
            self._context = ExecutionContext('reference')
            self.execution_id = self._context.identity
            self.plan_id = json_sha256(content_record(dict(schema='atlas.w09-water.v1', geometry=self.geometry.signature,
                execution=self.execution_id, shoreline='one-sided-wet-contact',
                spill_ties='lowest-level-then-stable-basin', intervals=LIMIT)), _json)
            self._n = len(self.geometry.bed_m)
            self._cells = tuple(np.asarray(c, dtype=int) for c in self.geometry.basin_cells)
        except BaseException:
            self.close()
            raise

    _thread_refusal = 'water model closed or driven from a different thread'
    _check = _check_owner_thread

    _reentrant_message = 'reentrant water operation'
    _operation_error = TectonicsError
    _operation = _prepared_operation

    def _vector(self, value, name):
        shape = input_shape(value, name)
        if shape == ():
            a = np.full(self._n, scalar(value, name, nonnegative=True))
            a[self.geometry.areas_m2 == 0] = 0
        elif shape == (self._n,):
            a = snapshot(value, name, nonnegative=True)
        else:
            raise TectonicsError(name+': scalar or one value per cell required')
        return a

    def _validate(self, state):
        _balance(state.initial_total_m3, state.supplied_m3, _sum(state.water_m3),
                 state.subsurface_m3, state.evaporated_m3, state.exported_m3)

    def _cells_for(self, members):
        return np.concatenate([self._cells[b] for b in sorted(members)])

    def _volume(self, cells, level):
        z,area,capacity=self._table(cells)
        index=int(np.searchsorted(z,level,side='right'))-1
        return 0. if index < 0 else float(capacity[index]+area[index]*(level-z[index]))

    def _table(self, cells):
        key=tuple(sorted(int(i) for i in cells))
        if key in self._hypsometry:
            self._hypsometry.move_to_end(key)
            return self._hypsometry[key]
        g=self.geometry
        positive=cells[g.areas_m2[cells]>0]
        z=np.unique(g.bed_m[positive])
        area=np.array([_sum(g.areas_m2[positive][g.bed_m[positive]<=h]) for h in z])
        capacity=np.array([_sum(g.areas_m2[positive]*np.maximum(h-g.bed_m[positive],0.)) for h in z])
        table=(z,area,capacity)
        if len(self._hypsometry)>=256:
            self._hypsometry.popitem(last=False)
        self._hypsometry[key]=table
        return table

    def _level(self, cells, volume):
        z,area,capacity=self._table(cells)
        if volume <= 0:
            return float(z[0])
        index=int(np.searchsorted(capacity,volume,side='right'))-1
        return float(z[index]+(volume-capacity[index])/area[index])

    def _equilibrate(self, water, cancel=None):
        """Finite-volume fill/spill/merge; rebuilding occupancy permits drawdown."""
        g = self.geometry
        groups = {i: {i} for i in range(len(self._cells))}
        volumes = {i: _sum(water[c]) for i, c in enumerate(self._cells)}
        owner = {i: i for i in groups}
        export = _sum(water[g.basin_of < 0])
        edges = sorted(g.saddles, key=lambda e: (e[2], e[0], e[1]))
        for iteration in range(1+4*(len(groups)+1)*(len(edges)+1)):
            check_event_or_callable(cancel, 'constitutive work cancelled')
            changed = False
            for a, b, sill in edges:
                a = owner[a]
                b = owner[b] if b >= 0 else b
                if a == b:
                    continue
                ca = self._cells_for(groups[a]); ha = self._level(ca, volumes[a])
                if b < 0:
                    capacity = self._volume(ca, sill)
                    if volumes[a] > capacity:
                        export += volumes[a]-capacity
                        volumes[a] = capacity
                        changed = True
                    continue
                cb = self._cells_for(groups[b]); hb = self._level(cb, volumes[b])
                # Merge only when there is water ABOVE the saddle; equality is
                # resolved one-sided by the current forcing (allows split/drain).
                if min(ha, hb) >= sill-_tol(sill) and max(ha, hb) > sill+_tol(sill):
                    target, donor = min(a, b), max(a, b)
                    groups[target] |= groups.pop(donor)
                    volumes[target] += volumes.pop(donor)
                    for leaf in groups[target]:
                        owner[leaf] = target
                    changed = True
                    break
                for donor, receiver, cells, height in ((a,b,ca,ha), (b,a,cb,hb)):
                    capacity = self._volume(cells, sill)
                    if height > sill+_tol(sill) and volumes[donor] > capacity:
                        excess = volumes[donor]-capacity
                        volumes[donor] = capacity
                        volumes[receiver] += excess
                        changed = True
                        break
                if changed:
                    break
            if not changed:
                break
        else:
            raise TectonicsError('finite lake fill/spill did not converge')
        result = np.zeros(self._n)
        pools = []
        for key in sorted(groups):
            cells = self._cells_for(groups[key])
            level = self._level(cells, volumes[key])
            result[cells] = g.areas_m2[cells]*np.maximum(level-g.bed_m[cells], 0.)
            pools.append((groups[key], cells, level, volumes[key]))
        if abs(_sum(water)-_sum(result)-export) > 128*EPS*(_sum(water)+_sum(result)+export):
            raise TectonicsError('lake redistribution precision loss')
        return result, export, pools

    def _rates(self, pools, forcing):
        # At a represented shoreline a receding cell is dry, not a permanently
        # evaporating patch. If the two one-sided forcing rates straddle zero,
        # resolve the zero-storage contact by a wet-duration fraction. This
        # books the actual supplied/lost water without nudging physical heights.
        fractions=np.ones(self._n)
        contacts=set()
        def settled(answer):
            scale=math.fsum(abs(x) for x in answer[1])
            groups=[(*p[:4],0.) if frozenset(p[0]) in contacts and
                    abs(p[4]) <= 128*EPS*scale else p for p in answer[0]]
            return groups,answer[1]
        result=self._raw_rates(pools,forcing,fractions)
        for _ in range(2*self._n+1):
            target=None
            for members,cells,h,volume,rate in result[0]:
                shore=cells[(np.abs(self.geometry.bed_m[cells]-h)<=_tol(h)) &
                            (self.geometry.areas_m2[cells]>0) & (fractions[cells]>0)]
                if volume > 0 and rate < 0 and len(shore):
                    target=(members,shore); break
            if target is None:
                return result
            members,shore=target
            high=float(fractions[shore[0]]); fractions[shore]=0.
            lower=settled(self._raw_rates(pools,forcing,fractions))
            def rate_for(answer):
                return _sum(p[4] for p in answer[0] if p[0] & members)
            if rate_for(lower) <= 0:
                result=lower; continue
            low=0.
            for _ in range(54):
                middle=(low+high)/2; fractions[shore]=middle
                answer=self._raw_rates(pools,forcing,fractions)
                if rate_for(answer)>0:
                    low=middle
                else:
                    high=middle
            fractions[shore]=(low+high)/2
            contacts.add(frozenset(members))
            result=settled(self._raw_rates(pools,forcing,fractions))
        raise TectonicsError('shoreline active set did not converge')

    def _raw_rates(self, pools, forcing, shoreline_fractions):
        """Solve the ideal-sill active set, descending in water level.

        Equality components absorb simultaneous losses BEFORE exporting surplus.
        A component with net drawdown separates at its exposed saddles.
        """
        g = self.geometry
        runoff, rain, evap, infil, boundary = forcing
        count = len(pools)
        leaf_owner = {b:i for i,p in enumerate(pools) for b in p[0]}
        wet = np.zeros(self._n)
        for _, cells, h, _ in pools:
            wet[cells] = ((g.bed_m[cells] <= h+_tol(h)) & (g.areas_m2[cells] > 0)).astype(float)
            shore=cells[np.abs(g.bed_m[cells]-h)<=_tol(h)]
            wet[shore]*=shoreline_fractions[shore]
        source = g.areas_m2*(wet*rain+(1-wet)*runoff)+boundary
        es = wet*evap*g.areas_m2
        fs = wet*infil*g.areas_m2
        rates = np.array([_sum(source[p[1]]-es[p[1]]-fs[p[1]]) for p in pools])
        export = _sum(source[g.basin_of < 0])
        adj = [[] for _ in pools]
        exits = [[] for _ in pools]
        for a,b,sill in g.saddles:
            i = leaf_owner[a]; j = leaf_owner[b] if b >= 0 else b
            if i == j:
                continue
            if j < 0:
                if abs(pools[i][2]-sill) <= _tol(sill):
                    exits[i].append((sill, j))
                continue
            hi, hj = pools[i][2], pools[j][2]
            if abs(hi-hj) <= _tol(hi,hj) and hi >= sill-_tol(sill):
                adj[i].append(j); adj[j].append(i)
            elif hi >= sill-_tol(sill) and hj < hi:
                exits[i].append((sill,j))
            elif hj >= sill-_tol(sill) and hi < hj:
                exits[j].append((sill,i))
        seen = set(); components = []
        for i in range(count):
            if i in seen:
                continue
            todo=[i]; seen.add(i); component=[]
            while todo:
                j=todo.pop(); component.append(j)
                for k in sorted(adj[j]):
                    if k not in seen:
                        seen.add(k); todo.append(k)
            components.append(sorted(component))
        output=[]
        for component in sorted(components, key=lambda c:(-pools[c[0]][2],c[0])):
            total = _sum(rates[component])
            available_exits = sorted((sill,target) for i in component for sill,target in exits[i])
            if total >= 0:
                members=set().union(*(pools[i][0] for i in component))
                cells=self._cells_for(members)
                if available_exits:
                    target=available_exits[0][1]
                    if target < 0:
                        export += total
                    else:
                        rates[target] += total
                    total=0.
                output.append((members,cells,pools[component[0]][2],
                               _sum(pools[i][3] for i in component),total))
            else:
                # Route each surplus to the first reachable deficit, never past
                # a receding lake. Stable BFS resolves the ideal-law tie.
                for start in component:
                    while rates[start] > 0:
                        todo=[start]; visited={start}; found=None
                        for node in todo:
                            if rates[node] < 0:
                                found=node; break
                            for other in sorted(adj[node]):
                                if other not in visited:
                                    visited.add(other); todo.append(other)
                        transfer=min(rates[start], -rates[found])
                        rates[start]-=transfer; rates[found]+=transfer
                for i in component:
                    members,cells,h,volume=pools[i]
                    rate=float(rates[i])
                    if volume == 0 and rate < 0:
                        demand=_sum(es[cells]+fs[cells])
                        if demand:
                            fraction=max(0.,(demand+rate)/demand)
                            es[cells]*=fraction; fs[cells]*=fraction
                        rate=0.
                    output.append((members,cells,h,volume,rate))
        return output, (_sum(source), _sum(es), _sum(fs), export)

    def _event_dt(self, groups, maximum):
        g=self.geometry; dt=maximum
        for members,cells,h,volume,rate in groups:
            if rate == 0:
                continue
            candidates=list(g.bed_m[cells][g.areas_m2[cells]>0])
            for a,b,sill in g.saddles:
                if a in members or b in members:
                    candidates.append(sill)
            if rate > 0:
                heights=[float(v) for v in candidates if v > h+_tol(h,v)]
                if heights:
                    delta=self._volume(cells,min(heights))-volume
                    if delta > 0:
                        dt=min(dt,delta/rate)
            else:
                heights=[float(v) for v in candidates if v < h-_tol(h,v)]
                target=max(heights) if heights else h
                remaining=self._volume(cells,target) if heights else 0.
                if volume > remaining:
                    dt=min(dt,(volume-remaining)/(-rate))
        return dt

    def _new(self, old, water, *, time_s=None, supplied=0., evaporated=0.,
             infiltrated=0., exported=0., intervals=1, event_id=None):
        return WaterState(water, time_s=old.time_s if time_s is None else time_s,
            subsurface_m3=old.subsurface_m3+infiltrated,
            evaporated_m3=old.evaporated_m3+evaporated,
            exported_m3=old.exported_m3+exported, supplied_m3=old.supplied_m3+supplied,
            initial_total_m3=old.initial_total_m3,
            accepted_intervals=old.accepted_intervals+intervals,
            geometry_id=self.geometry.signature,execution_id=self.execution_id,
            parent_id=old.state_id,event_id=event_id)

    def initialise(self, water_m3=None, *, time_s=0, subsurface_m3=0):
        with self._operation():
            w=self._vector(0 if water_m3 is None else water_m3,'initial water')
            sub=scalar(subsurface_m3,'initial subsurface water',nonnegative=True)
            water,export,_=self._equilibrate(w)
            return WaterState(water,time_s=time_s,subsurface_m3=sub,evaporated_m3=0,
                exported_m3=export,supplied_m3=0,initial_total_m3=_sum(w)+sub,
                accepted_intervals=0,geometry_id=self.geometry.signature,
                execution_id=self.execution_id,event_id='initialise')

    def accumulate_runoff(self, runoff_m_s, *, cancel=None):
        """Dry-network Q in m3/s, stopping at pits/outlets; no invented lake flow.

        This is the fixed-geometry accumulation control. Evolving lake releases
        belong to advance's integrated account, not this diagnostic array.
        """
        with self._operation(cancel):
            g=self.geometry
            q=np.array(self._vector(runoff_m_s,'runoff')*g.areas_m2,copy=True)
            for i in g.order:
                check_event_or_callable(cancel, 'constitutive work cancelled')
                receiver=int(g.receivers[i])
                if receiver != i:
                    q[receiver]+=q[i]
            return frozen(q)

    def add_water(self, state, by_cell_m3, *, source_id, cancel=None):
        with self._operation(cancel):
            self._validate(state); _name(source_id,'water supply source')
            w=self._vector(by_cell_m3,'supplied water')
            water,export,_=self._equilibrate(state.water_m3+w,cancel)
            return self._new(state,water,supplied=_sum(w),exported=export,
                             event_id=json_sha256(dict(source=source_id,volumes=w.tolist()), _json))

    def advance(self, state, duration_s, *, runoff_m_s=0, rain_m_s=None,
                evaporation_m_s=0, infiltration_m_s=0, boundary_inflow_m3_s=0,
                forcing_id, cancel=None):
        with self._operation(cancel):
            self._validate(state); _name(forcing_id,'water forcing source')
            duration=scalar(duration_s,'water interval',positive=True)
            r=self._vector(runoff_m_s,'runoff')
            # Omitting rain explicitly means the same supplied water-depth flux
            # over wet and dry footprints, NOT a inferred global climate.
            forcing=(r,self._vector(r if rain_m_s is None else rain_m_s,'lake rain'),
                self._vector(evaporation_m_s,'evaporation'),self._vector(infiltration_m_s,'infiltration'),
                self._vector(boundary_inflow_m3_s,'boundary inflow'))
            key=json_sha256(dict(parent=state.state_id,duration=duration,source=forcing_id,
                           forcing=[a.tolist() for a in forcing]), _json)
            if self._latest is not None and self._latest[0] == key:
                self._stats['latest_hits']+=1
                return self._latest[1]
            water=np.array(state.water_m3,copy=True)
            elapsed=0.; terms=[[],[],[],[]]; intervals=0
            while elapsed < duration:
                check_event_or_callable(cancel, 'constitutive work cancelled')
                if state.accepted_intervals+intervals >= LIMIT:
                    raise TectonicsError('cumulative accepted water interval limit')
                water,escaped,pools=self._equilibrate(water,cancel)
                terms[3].append(escaped)
                groups,rates=self._rates(pools,forcing)
                dt=self._event_dt(groups,duration-elapsed)
                candidate=np.zeros(self._n)
                for members,cells,h,volume,rate in groups:
                    v=volume+rate*dt
                    # Exact event cancellation may leave only signed roundoff.
                    if v < 0:
                        if v < -128*EPS*(abs(volume)+abs(rate*dt)):
                            raise TectonicsError('negative candidate lake volume')
                        v=0.
                    level=self._level(cells,v)
                    candidate[cells]=self.geometry.areas_m2[cells]*np.maximum(level-self.geometry.bed_m[cells],0.)
                for target,rate in zip(terms,rates):
                    target.append(dt*rate)
                water,escaped,_=self._equilibrate(candidate,cancel)
                terms[3].append(escaped)
                next_elapsed=elapsed+dt
                elapsed=min(duration,next_elapsed); intervals+=1
            supplied,evaporated,infiltrated,exported=map(math.fsum,terms)
            out=self._new(state,water,time_s=state.time_s+duration,supplied=supplied,
                evaporated=evaporated,infiltrated=infiltrated,exported=exported,
                intervals=intervals,event_id=key)
            self._check(cancel)
            self._latest=(key,out)
            self._stats['computed_intervals']+=intervals
            return out

    def relocate(self, state, previous_geometry, *, source_id, cancel=None):
        """Same finite cells/areas, changed bed/connectivity; no invented overlap."""
        with self._operation(cancel):
            _name(source_id,'geometry transition source')
            old=previous_geometry; g=self.geometry
            water,export,_=self._equilibrate(state.water_m3,cancel)
            return self._new(state,water,exported=export,event_id=json_sha256(dict(
                source=source_id,old=old.signature,new=g.signature), _json))

    def checkpoint(self, state, *, cancel=None):
        with self._operation(cancel):
            self._validate(state)
            key=json_sha256(dict(plan=self.plan_id,state=state.state_id), _json)
            meta=dict(schema='atlas.w09-water-checkpoint.v1',plan=self.plan_id,
                      state_id=state.state_id,state=state.descriptor())
            cast('ArrayStore', self.store).put(key,{'water':state.water_m3},meta,
                           publication_check=lambda:self._check(cancel))
            return key

    def restore(self, checkpoint_id, *, cancel=None):
        with self._operation(cancel):
            meta=cast(dict, cast('ArrayStore', self.store).metadata(checkpoint_id))
            arrays=cast(dict, cast('ArrayStore', self.store).get(checkpoint_id,budget=self._resource))
            out=WaterState(arrays['water'],**meta['state'])
            self._validate(out)
            if out.state_id != meta['state_id'] or checkpoint_id != json_sha256(dict(plan=self.plan_id,state=out.state_id), _json):
                raise TectonicsError('water checkpoint content mismatch')
            self._stats['restored_states']+=1
            return out

    statistics = _budget_statistics

    def close(self):
        if not self._closed:
            self._closed=True; self._latest=None; self._hypsometry.clear()
            try:
                if self._context is not None:
                    self._context.close()
            finally:
                if self._guard is not None:
                    self._guard.__exit__(None,None,None); self._guard=None

    def __enter__(self):
        self._check(); return self

    def __exit__(self,*_):
        self.close()
