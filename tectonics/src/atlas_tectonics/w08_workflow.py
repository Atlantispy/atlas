"""Chronological W08 finite stocks, exact regime events and atomic restart.

Prescribed affine regional footprints and homogeneous finite material stocks.
Steady wedge temperature is a separate accepted diagnostic, not a transient heat
history. A regime label never supplies missing kinematics or a continental law.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import threading
from time import perf_counter

import numpy as np

from ._validation import TectonicsError, scalar, frozen
from .materials import _json, _name
from .constitutive import _cancel
from .geometry import PlanarGeometry
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .storage import ArrayStore
from .spreading import _within_budget
from .stokes_execution import _native_lease
from .transform import AffineMotionInterval, PreparedAffineMotion
from .w08_inventory import W08Inventory, advance_magmatic, advance_retirement
from .w08_region import W08Region
from .subduction_materials import RetirementExhaustionError
from .magmatic_transfer import MagmaticExhaustionError


CAP = 128*1024**2
REGIMES = ('shortening', 'transform', 'oblique', 'subduction', 'magmatism', 'cessation')
OWNERS = dict(material='w08-finite-inventory', geometry='w08-affine-region',
              thermal='stored-enthalpy-not-extra-heating', load='current-minus-reference-column-mass',
              emplacement='terminal-stock-view-not-second-inventory')


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _array_id(a):
    h = hashlib.sha256(_json((a.shape, a.dtype.str)))
    h.update(a.tobytes())
    return h.hexdigest()


@dataclass(frozen=True, init=False)
class RegimeInterval:
    """One supplied constant-forcing interval; transitions occur at its start."""
    end_time_s: float
    regime: str
    source_id: str
    _record: bytes

    def __init__(self, end_time_s, regime, source_id, *, transition=None,
                 motion=None, retirement=None, magmatism=None):
        if regime not in REGIMES:
            raise TectonicsError('unsupported regime, including unspecified continental entry/underthrust')
        _name(source_id, 'regime source')
        end = scalar(end_time_s, 'regime end')
        if retirement is not None and magmatism is not None:
            raise TectonicsError('simultaneous coupled retirement/magma demands require an explicit coupled law')
        if (regime == 'subduction') != (retirement is not None):
            raise TectonicsError('subduction needs its explicit finite retirement contract')
        if (regime == 'magmatism') != (magmatism is not None):
            raise TectonicsError('magmatism needs its explicit finite transfer contract')
        if regime in ('shortening', 'transform', 'oblique') and motion is None:
            raise TectonicsError('kinematic regime requires full-vector prescribed motion')
        if regime == 'cessation' and motion is not None:
            raise TectonicsError('cessation cannot silently keep moving the represented region')
        if motion is not None:
            if type(motion) is not dict or set(motion) != {'gradient_s','velocity_m_s','anchor_m'}:
                raise TectonicsError('full gradient, velocity and anchor required')
            m = AffineMotionInterval(end, motion['gradient_s'], motion['velocity_m_s'],
                                     motion['anchor_m'], source_id)
            if regime == 'shortening' and (np.any(m.gradient_s-np.diag(np.diag(m.gradient_s))) or
                    m.gradient_s[0,0] > 0 or m.gradient_s[1,1] != 0):
                raise TectonicsError('shortening uses the supported plane-strain contraction')
            motion = {k:m.descriptor()[k] for k in motion}
        for value, keys, label in ((retirement, {'selected_node_ids','destination_ids','parameters'}, 'retirement'),
                (magmatism, {'selected_node_ids','rates_kg_s','heat_w'}, 'magmatism')):
            if value is not None and (type(value) is not dict or set(value) != keys):
                raise TectonicsError(label+' needs an exact explicit input contract')
        if transition is not None:
            keys = {'event_id','from_regime','to_regime','boundary_id','geometry_policy',
                    'polarity','coupling_source','kinematics_source','thermal_source'}
            if type(transition) is not dict or set(transition) != keys:
                raise TectonicsError('dated transition requires geometry, polarity, coupling and thermal provenance')
            if transition['from_regime'] not in REGIMES or transition['to_regime'] != regime:
                raise TectonicsError('unsupported or mismatched transition regime')
            if transition['geometry_policy'] != 'continuous':
                raise TectonicsError('geometry jumps require a separate conservative transfer law')
            for k,v in transition.items(): _name(v, 'transition '+k)
        record = dict(end_time_s=end,regime=regime,source_id=source_id,transition=transition,
                      motion=motion,retirement=retirement,magmatism=magmatism)
        if len(_json(record)) > 131072: raise TectonicsError('regime input metadata exceeds128KiB')
        for k,v in dict(end_time_s=end,regime=regime,source_id=source_id,_record=_json(record)).items():
            object.__setattr__(self,k,v)

    def descriptor(self): return json.loads(self._record)


@dataclass(frozen=True)
class W08Output:
    inventory: W08Inventory
    polygons: tuple
    reference_polygons: tuple
    deformation_gradient: np.ndarray
    regional: object
    interval_index: int
    checkpoint_id: str
    _receipt: bytes

    def descriptor(self): return json.loads(self._receipt)

    @property
    def output_id(self):
        return _hash(dict(receipt=self.descriptor(),inventory=self.inventory.inventory_id,
                          geometry=[g.geometry_id for g in self.polygons],
                          reference=[g.geometry_id for g in self.reference_polygons],
                          deformation=_array_id(self.deformation_gradient)))


class W08ExhaustionError(TectonicsError):
    """The valid finite-stock endpoint was committed; no continuation invented."""
    def __init__(self,output):
        self.output=output
        self.exhaustion_time_s=output.inventory.time_s
        super().__init__('W08 stopped at exact finite-stock exhaustion at '+repr(self.exhaustion_time_s)+
                         ' s; the endpoint is retained, but continuation needs a supplied next event')


class PreparedW08Workflow:
    """Serial physical owner; retains only one output and one prepared motion.

    Checkpoints exist only after complete event intervals. Observation requests
    cannot create half-applied transitions. Reopening a store verifies the chain
    before continuing from its last endpoint, without re-evaluating its transfers.
    """
    def __setattr__(self,name,value):
        if name in ('initial','region','intervals','store','plan_id','execution_id','thermodynamics') and hasattr(self,name):
            raise AttributeError('prepare a new source-bound W08 workflow')
        object.__setattr__(self,name,value)

    def __init__(self, initial, region, intervals, *, source_id, thermodynamics=None,
                 store=None, budget=None, cancel=None):
        if type(initial) is not W08Inventory or type(region) is not W08Region:
            raise TectonicsError('typed W08 initial inventory and region required')
        if type(intervals) is not tuple or not 1 <= len(intervals) <= 256 or any(type(i) is not RegimeInterval for i in intervals):
            raise TectonicsError('one to256 complete event intervals required')
        if store is not None and not isinstance(store,ArrayStore): raise TectonicsError('ArrayStore required')
        _name(source_id,'workflow source')
        start = initial.time_s; previous = None; events = set()
        for interval in intervals:
            d = interval.descriptor(); t = d['transition']
            if interval.end_time_s <= start: raise TectonicsError('intervals must increase from the source epoch')
            if previous is None:
                if t is not None: raise TectonicsError('initial regime has no preceding workflow regime')
            elif previous != interval.regime and t is None:
                raise TectonicsError('regime changes require a dated transition')
            if t is not None:
                if t['from_regime'] != previous or t['event_id'] in events:
                    raise TectonicsError('transition old regime or unique event identity mismatch')
                if t['thermal_source'] != initial.enthalpy_source:
                    raise TectonicsError('transition thermal convention mismatch')
                events.add(t['event_id'])
            if d['retirement'] is not None:
                p = d['retirement']['parameters']
                if p.get('frame_id') != region.frame_id or p.get('epoch_id') != region.epoch_id:
                    raise TectonicsError('retirement and regional spatial/time frames differ')
            start,previous = interval.end_time_s,interval.regime
        self._resource = WorkBudget(CAP,parent=select_budget(budget))
        if store is not None: _within_budget(self._resource,store._budget)
        self._owner = threading.get_ident(); self._closed = self._active = False
        self.initial,self.region,self.intervals,self.store = initial,region,intervals,store
        self.thermodynamics = thermodynamics
        self._context = self._motion = self._guard = self._current_guard = None
        self._current = None
        self._stats = dict(computed_intervals=0,restored_outputs=0,latest_hits=0,
                           physics_seconds=0.,storage_seconds=0.)
        self._guard = self._resource.reserve(2*1024**2+4*initial.nbytes+region.nbytes+sum(len(i._record) for i in intervals),
                                            category='w08-workflow-prepared')
        self._guard.__enter__()
        try:
            self._context = ExecutionContext('scipy'); self.execution_id = self._context.identity
            # Validates represented owners before any state is accepted.
            region.regional_view(initial,region.polygons,reference_inventory=initial,budget=self._resource,cancel=cancel)
            histories = []
            for i in intervals:
                m = i.descriptor()['motion'] or dict(gradient_s=[[0.,0.],[0.,0.]],velocity_m_s=[0.,0.],anchor_m=[0.,0.])
                histories.append(AffineMotionInterval(i.end_time_s,**m,source_id=i.source_id))
            self._motion = PreparedAffineMotion(region.polygons,tuple(histories),parcel_ids=region.parcel_ids,
                time_s=initial.time_s,source_id=source_id,budget=self._resource,cancel=cancel)
            self._binding = dict(schema='atlas.w08-workflow.v1',source_status='WORKING NON-CANON',
                source_id=source_id,initial_id=initial.inventory_id,region_id=region.region_id,
                intervals=[i.descriptor() for i in intervals],execution=self.execution_id,
                thermodynamics=None if thermodynamics is None else thermodynamics.thermodynamics_id,
                owners=OWNERS,limits=dict(work_bytes=CAP,intervals=256,native_threads=1))
            self.plan_id = _hash(self._binding)
            self._check(cancel)
        except BaseException:
            self.close(); raise

    def _check(self,cancel=None):
        if self._closed: raise TectonicsError('W08 workflow closed')
        if threading.get_ident() != self._owner: raise TectonicsError('drive W08 from its owning thread')
        _cancel(cancel); self._context.verify()

    @contextmanager
    def _operation(self,cancel=None):
        self._check(cancel)
        if self._active: raise TectonicsError('reentrant W08 spending refused')
        self._active = True
        try:
            with _native_lease():
                yield
            self._check(cancel)
        finally: self._active = False

    def _index(self,index):
        if type(index) is not int or not 0 <= index < len(self.intervals):
            raise TectonicsError('complete event interval index required; no mid-event restart')
        return index

    def checkpoint_id(self,index):
        return _hash(dict(plan=self.plan_id,index=self._index(index)))

    def statistics(self): return dict(self._stats,budget=self._resource.statistics())

    def _validate(self,out):
        i = self._index(out.interval_index); d = out.descriptor(); inv = out.inventory
        if (inv.node_ids != self.initial.node_ids or inv.node_kinds != self.initial.node_kinds or
                inv.component_ids != self.initial.component_ids or
                inv.enthalpy_source != self.initial.enthalpy_source or
                inv.origin_ids != self.initial.origin_ids or
                not np.array_equal(inv.formation_time_s,self.initial.formation_time_s) or
                inv.time_s != d['end_time_s']):
            raise TectonicsError('restored inventory catalogue/time/thermal provenance mismatch')
        if (d['owners'] != OWNERS or d['plan_id'] != self.plan_id or d['execution'] != self.execution_id or
                d['interval_index'] != i or d['end_time_s'] != inv.time_s or d['phase'] != 'complete'):
            raise TectonicsError('incomplete or wrong-owner event checkpoint')
        expected_events = [s.descriptor()['transition']['event_id'] for s in self.intervals[:i+1]
                           if s.descriptor()['transition'] is not None]
        if d['applied_event_ids'] != expected_events:
            raise TectonicsError('event cursor mismatch or replayed transition')
        empty = [name for name,m,old in zip(inv.node_ids,inv.mass_kg,self.initial.mass_kg) if m == 0 and old > 0]
        if d['exhausted_node_ids'] != empty: raise TectonicsError('exhausted source state mismatch')
        self._event_endpoint(i,d)
        if type(d['accepted_intervals']) is not int or not i+1 <= d['accepted_intervals'] <= 256:
            raise TectonicsError('cumulative accepted-interval ceiling exceeded')
        self._validate_history(d,inv)
        for j in range(len(inv.component_ids)):
            values = [*inv.component_mass_kg[:,j], *(-self.initial.component_mass_kg[:,j])]
            if abs(math.fsum(values)) > 128*np.finfo(float).eps*math.fsum(map(abs,values)):
                raise TectonicsError('cross-regime component account does not close')
        q = scalar(d['cumulative_external_heat_j'],'booked heat')
        aq = scalar(d['cumulative_absolute_heat_j'],'absolute heat',nonnegative=True)
        values = [*inv.enthalpy_j,*(-self.initial.enthalpy_j),-q]
        if abs(math.fsum(values)) > 128*np.finfo(float).eps*(math.fsum(map(abs,values))+aq):
            raise TectonicsError('cross-regime enthalpy account does not close')
        motion = self._motion.evaluate(inv.time_s)
        if (tuple(g.geometry_id for g in out.polygons) != tuple(g.geometry_id for g in motion.polygons) or
                tuple(g.geometry_id for g in out.reference_polygons) != tuple(g.geometry_id for g in self.region.polygons) or
                not np.array_equal(out.deformation_gradient,motion.deformation_gradient)):
            raise TectonicsError('restored current/reference geometry or deformation mismatch')

    def _validate_history(self,record,inventory):
        """Reconcile tagged transfers, not replay a physical solver or its flux."""
        history = record['transfer_history']
        i = record['interval_index']
        if type(history) is not list or len(history) != i+1:
            raise TectonicsError('incomplete tagged transfer provenance')
        c = self.initial.component_mass_kg.copy(); e = self.initial.enthalpy_j.copy()
        cscale = abs(c); escale = abs(e); total_steps = 0
        node_index = {n:j for j,n in enumerate(self.initial.node_ids)}
        heat_total = []; absolute_heat = []
        for j,r in enumerate(history):
            spec = self.intervals[j].descriptor()
            end = record['end_time_s'] if j==i else self.intervals[j].end_time_s
            duration = end-(self.initial.time_s if j==0 else self.intervals[j-1].end_time_s)
            if j==i and record['stopped_at_exhaustion']: duration=r['duration_s']
            if spec['retirement'] is None and spec['magmatism'] is None:
                if r is not None: raise TectonicsError('unexpected transfer in kinematic/cessation interval')
                total_steps += 1; continue
            if (type(r) is not dict or r.get('source_id') != spec['source_id'] or r.get('duration_s') != duration):
                raise TectonicsError('transfer event source or duration mismatch')
            selected = r['selected_node_ids']
            if spec['retirement'] is not None:
                a = spec['retirement']
                if selected != a['selected_node_ids'] or r['destination_ids'] != a['destination_ids']:
                    raise TectonicsError('retirement owner mapping mismatch')
                dc = np.asarray(r['transferred_component_mass_kg'],float)
                de = np.asarray(r['transferred_enthalpy_j'],float)
                if dc.shape != (3,len(selected),c.shape[1]) or de.shape != (3,len(selected)):
                    raise TectonicsError('retirement receipt shape mismatch')
                for dest,row in zip(a['destination_ids'],range(3)):
                    for src,col in zip(selected,range(len(selected))):
                        si,di = node_index[src],node_index[dest]
                        c[si] -= dc[row,col]; c[di] += dc[row,col]
                        e[si] -= de[row,col]; e[di] += de[row,col]
                        cscale[si] += dc[row,col]; cscale[di] += dc[row,col]
                        escale[si] += abs(de[row,col]); escale[di] += abs(de[row,col])
                total_steps += 1
            else:
                a = spec['magmatism']
                if selected != a['selected_node_ids']: raise TectonicsError('magma owner mapping mismatch')
                rates = np.asarray(a['rates_kg_s'],float)
                edges = [(selected[x],selected[y]) for x,y in zip(*np.nonzero(rates))]
                if r['edge_ids'] != [list(edge) for edge in edges]: raise TectonicsError('magma edge mapping mismatch')
                dc = np.asarray(r['transferred_component_mass_kg'],float).reshape(len(edges),c.shape[1])
                de = np.asarray(r['transferred_enthalpy_j'],float)
                heat = np.asarray(r['external_heat_j'],float)
                expected_heat = np.zeros(len(selected)) if a['heat_w'] is None else np.asarray(a['heat_w'],float)*duration
                if not np.array_equal(heat,expected_heat): raise TectonicsError('external heat receipt mismatch')
                if de.shape != (len(edges),): raise TectonicsError('edge heat shape mismatch')
                for edge,k in zip(edges,range(len(edges))):
                    si,di = (node_index[n] for n in edge)
                    c[si] -= dc[k]; c[di] += dc[k]; e[si] -= de[k]; e[di] += de[k]
                    cscale[si] += dc[k]; cscale[di] += dc[k]
                    escale[si] += abs(de[k]); escale[di] += abs(de[k])
                for node,q in zip(selected,heat):
                    e[node_index[node]] += q; escale[node_index[node]] += abs(q)
                heat_total.extend(heat); absolute_heat.extend(abs(heat))
                steps = r['kernel']['accepted_intervals']
                if type(steps) is not int or not 1 <= steps <= 256: raise TectonicsError('invalid accepted magma steps')
                total_steps += steps
            if not np.isfinite(dc).all() or np.any(dc<0) or not np.isfinite(de).all():
                raise TectonicsError('invalid extensive transfer receipt')
        tol = 128*np.finfo(float).eps
        if (np.any(abs(c-inventory.component_mass_kg)>tol*(cscale+abs(inventory.component_mass_kg))) or
                np.any(abs(e-inventory.enthalpy_j)>tol*(escale+abs(inventory.enthalpy_j))) or
                total_steps != record['accepted_intervals'] or
                math.fsum(heat_total) != record['cumulative_external_heat_j'] or
                math.fsum(absolute_heat) != record['cumulative_absolute_heat_j']):
            raise TectonicsError('tagged transfer/stock/heat history does not reconcile')

    def _event_endpoint(self,index,record):
        expected=self.intervals[index].end_time_s
        if type(record.get('stopped_at_exhaustion')) is not bool: raise TectonicsError('missing event completion state')
        if not record['stopped_at_exhaustion']:
            if record['end_time_s']!=expected: raise TectonicsError('mid-event output refused')
            return
        start=self.initial.time_s if index==0 else self.intervals[index-1].end_time_s
        r=record['transfer_history'][-1]
        if (not start < record['end_time_s'] < expected or type(r) is not dict or
                r.get('exhaustion_duration_s') != r.get('duration_s') or
                start+r['duration_s'] != record['end_time_s'] or not r.get('exhausted_node_ids')):
            raise TectonicsError('unsupported partial interval is not an exact exhausted-stock event')

    def _compute(self,index,parent,cancel):
        s = self.intervals[index]; spec = s.descriptor()
        inv = self.initial if parent is None else parent.inventory
        duration = s.end_time_s-inv.time_s
        a = spec['retirement']; m = spec['magmatism']; receipt = None; stopped=False
        def transfer(dt):
            if a is not None:
                return advance_retirement(inv,tuple(a['selected_node_ids']),tuple(a['destination_ids']),dt,
                    source_id=s.source_id,parameters=a['parameters'],budget=self._resource,cancel=cancel)
            return advance_magmatic(inv,tuple(m['selected_node_ids']),m['rates_kg_s'],dt,
                    source_id=s.source_id,heat_w=m['heat_w'],thermodynamics=self.thermodynamics,
                    context=self._context,budget=self._resource,cancel=cancel)
        if a is not None or m is not None:
            try: candidate,receipt=transfer(duration)
            except (RetirementExhaustionError,MagmaticExhaustionError) as exhausted:
                duration=exhausted.exhaustion_duration_s
                if duration<=0: raise
                # The rejected branch did not spend anything. Compute exactly
                # once up to its declared feasibility event, publish, then stop.
                candidate,receipt=transfer(duration);stopped=True
            inv=candidate
        else:
            inv = inv.retime(s.end_time_s,source_id=s.source_id,budget=self._resource,cancel=cancel)
        motion = self._motion.evaluate(inv.time_s,cancel=cancel)
        view = self.region.regional_view(inv,motion.polygons,reference_inventory=self.initial,
                                       budget=self._resource,cancel=cancel)
        prior = None if parent is None else parent.descriptor()
        heat = [] if receipt is None else receipt.get('external_heat_j',[])
        history = ([] if prior is None else prior['transfer_history'])+[receipt]
        heat_entries = [q for r in history if r is not None for q in r['external_heat_j']]
        steps = 1 if m is None else receipt['kernel']['accepted_intervals']
        accepted = (0 if prior is None else prior['accepted_intervals'])+steps
        if accepted > 256: raise TectonicsError('joined history exceeds256 accepted intervals')
        record = dict(schema='atlas.w08-output.v1',source_status='WORKING NON-CANON',
            plan_id=self.plan_id,execution=self.execution_id,owners=OWNERS,
            interval_index=index,phase='complete',regime=s.regime,
            start_time_s=self.initial.time_s if index==0 else self.intervals[index-1].end_time_s,
            end_time_s=inv.time_s,stopped_at_exhaustion=stopped,parent_output_id=None if parent is None else parent.output_id,
            applied_event_ids=[x.descriptor()['transition']['event_id'] for x in self.intervals[:index+1]
                               if x.descriptor()['transition'] is not None],
            exhausted_node_ids=[n for n,m,old in zip(inv.node_ids,inv.mass_kg,self.initial.mass_kg) if m==0 and old>0],
            cumulative_external_heat_j=math.fsum(heat_entries),
            cumulative_absolute_heat_j=math.fsum(map(abs,heat_entries)),
            accepted_intervals=accepted,transfer_history=history)
        if len(_json(record)) > 512*1024: raise TectonicsError('bounded tagged event history exceeds512KiB')
        return W08Output(inv,motion.polygons,self.region.polygons,frozen(motion.deformation_gradient),view,
                         index,self.checkpoint_id(index),_json(record))

    def _pack(self,out):
        arrays = dict(components=out.inventory.component_mass_kg,enthalpy=out.inventory.enthalpy_j,
                      formation=out.inventory.formation_time_s,deformation=out.deformation_gradient,
                      reference_components=self.initial.component_mass_kg,reference_enthalpy=self.initial.enthalpy_j)
        for prefix,polygons in (('current',out.polygons),('reference',out.reference_polygons)):
            for j,g in enumerate(polygons): arrays[prefix+'_'+str(j)] = np.frombuffer(g.wkb,dtype=np.uint8)
        header = dict(schema='atlas.w08-checkpoint.v1',plan_id=self.plan_id,execution=self.execution_id,
            index=out.interval_index,checkpoint_id=out.checkpoint_id,parent_checkpoint_id=(
                None if out.interval_index==0 else self.checkpoint_id(out.interval_index-1)),
            output_id=out.output_id,inventory=out.inventory.descriptor(),receipt=out.descriptor(),
            arrays={k:_array_id(v) for k,v in arrays.items()})
        return arrays,dict(header,content_id=_hash(header))

    def _header(self,index,meta,parent):
        keys = {'schema','plan_id','execution','index','checkpoint_id','parent_checkpoint_id',
                'output_id','inventory','receipt','arrays','content_id'}
        if type(meta) is not dict or set(meta) != keys: raise TectonicsError('invalid W08 checkpoint envelope')
        header = {k:v for k,v in meta.items() if k!='content_id'}
        r = meta['receipt']
        if (meta['schema'] != 'atlas.w08-checkpoint.v1' or meta['plan_id'] != self.plan_id or
                meta['execution'] != self.execution_id or meta['index'] != index or
                meta['checkpoint_id'] != self.checkpoint_id(index) or meta['content_id'] != _hash(header) or
                meta['parent_checkpoint_id'] != (None if index==0 else self.checkpoint_id(index-1)) or
                type(r) is not dict or r.get('parent_output_id') != parent or
                r.get('phase') != 'complete' or r.get('interval_index') != index or
                r.get('owners') != OWNERS):
            raise TectonicsError('stale, partial or misbound W08 checkpoint')
        self._event_endpoint(index,r)

    def _scan(self,end,cancel):
        latest,meta,parent,gap = -1,None,None,False
        for i in range(end+1):
            _cancel(cancel); candidate = self.store.metadata(self.checkpoint_id(i))
            if candidate is None: gap=True; continue
            if gap: raise TectonicsError('partial W08 checkpoint history has a gap')
            self._header(i,candidate,parent)
            latest,meta,parent = i,candidate,candidate['output_id']
        return latest,meta

    def _restore(self,index,meta,cancel):
        # Store.get accounts decode work, not the caller-retained arrays after it
        # returns. Keep their known bounded shapes plus regional observation and
        # validation scratch admitted for the whole restore transaction.
        size = (8*self.initial.nbytes+4*self.region.nbytes+2*1024**2+
                32*len(self.region.node_ids)*len(self.region.parcel_ids)*len(self.initial.component_ids))
        with self._resource.reserve(size,category='w08-restore-retained-and-scratch'):
            return self._restore_payload(index,meta,cancel)

    def _restore_payload(self,index,meta,cancel):
        arrays = self.store.get(self.checkpoint_id(index),budget=self._resource)
        if arrays is None or set(arrays) != set(meta['arrays']) or any(_array_id(a)!=meta['arrays'][k] for k,a in arrays.items()):
            raise TectonicsError('corrupt, partial or changed W08 checkpoint arrays')
        d = meta['inventory']
        inv = W08Inventory(tuple(d['node_ids']),tuple(d['node_kinds']),tuple(d['component_ids']),
            arrays['components'],arrays['enthalpy'],source_id=d['source_id'],enthalpy_source=d['enthalpy_source'],
            time_s=d['time_s'],formation_time_s=arrays['formation'],origin_ids=tuple(d['origin_ids']),
            budget=self._resource,cancel=cancel)
        count = len(self.region.polygons)
        expected = {'components','enthalpy','formation','deformation','reference_components','reference_enthalpy'} | {
            prefix+'_'+str(j) for prefix in ('current','reference') for j in range(count)}
        if set(arrays) != expected: raise TectonicsError('checkpoint geometry count mismatch')
        if (not np.array_equal(arrays['reference_components'],self.initial.component_mass_kg) or
                not np.array_equal(arrays['reference_enthalpy'],self.initial.enthalpy_j)):
            raise TectonicsError('checkpoint reference stocks mismatch')
        groups = []
        for prefix in ('current','reference'):
            groups.append(tuple(PlanarGeometry.from_wkb(arrays[prefix+'_'+str(j)].tobytes(),
                frame_id=self.region.polygons[0].frame_id,budget=self._resource) for j in range(count)))
        view = self.region.regional_view(inv,groups[0],reference_inventory=self.initial,
                                        budget=self._resource,cancel=cancel)
        out = W08Output(inv,groups[0],groups[1],frozen(arrays['deformation']),view,index,
                        self.checkpoint_id(index),_json(meta['receipt']))
        if out.output_id != meta['output_id']: raise TectonicsError('checkpoint scientific state identity mismatch')
        self._validate(out); self._stats['restored_outputs'] += 1
        return out

    def _output_guard(self,out):
        size = (4*out.inventory.nbytes+out.deformation_gradient.nbytes+len(out._receipt)+
                sum(g.retained_bytes for g in out.polygons)+getattr(out.regional,'nbytes',0)+65536)
        guard = self._resource.reserve(size,category='w08-latest-output'); guard.__enter__()
        return guard

    def _adopt(self,out,guard=None):
        if guard is None: guard=self._output_guard(out)
        old = self._current_guard
        self._current,self._current_guard = out,guard
        if old is not None: old.__exit__(None,None,None)

    def load(self,index,*,checkpoint_id=None,cancel=None):
        self._index(index)
        with self._operation(cancel):
            # Explicit foreign checkpoint IDs must refuse, never be re-labelled
            # a cache miss after code, parameters or runtime change.
            if checkpoint_id is not None and checkpoint_id != self.checkpoint_id(index):
                raise TectonicsError('explicit checkpoint belongs to stale/different sources or runtime')
            if self.store is None:
                return self._current if self._current and self._current.interval_index==index else None
            last,meta = self._scan(index,cancel)
            if last != index: return None
            out = self._restore(index,meta,cancel); self._adopt(out); return out

    def run(self,*,through=None,cancel=None):
        end = len(self.intervals)-1 if through is None else self._index(through)
        with self._operation(cancel):
            current = self._current
            if current is not None and current.interval_index==end and self.store is None:
                if current.descriptor()['stopped_at_exhaustion']: raise W08ExhaustionError(current)
                self._stats['latest_hits'] += 1; return current
            if self.store is not None:
                last,meta = self._scan(end,cancel)
                current = None if last<0 else self._restore(last,meta,cancel)
                if current is not None: self._adopt(current)
            elif current is not None and current.interval_index>end:
                raise TectonicsError('earlier outputs are not retained; use an explicit checkpoint store')
            first = 0 if current is None else current.interval_index+1
            if current is not None and current.descriptor()['stopped_at_exhaustion']:
                raise W08ExhaustionError(current)
            for index in range(first,end+1):
                self._check(cancel); started = perf_counter()
                with self._resource.reserve(8*self.initial.nbytes+4*1024**2,category='w08-step-scratch'):
                    candidate = self._compute(index,current,cancel)
                    pending_guard=self._output_guard(candidate)
                    try:
                        self._validate(candidate)
                        self._stats['physics_seconds'] += perf_counter()-started
                        if self.store is not None:
                            started = perf_counter(); arrays,meta = self._pack(candidate)
                            self.store.put(candidate.checkpoint_id,arrays,meta,budget=self._resource,cancel=cancel,
                                           publication_check=lambda:self._check(cancel))
                            self._stats['storage_seconds'] += perf_counter()-started
                        self._check(cancel); self._adopt(candidate,pending_guard); pending_guard=None
                    finally:
                        if pending_guard is not None: pending_guard.__exit__(None,None,None)
                    self._stats['computed_intervals'] += 1; current = candidate
                    if current.descriptor()['stopped_at_exhaustion']: raise W08ExhaustionError(current)
            return current

    def close(self):
        if self._closed: return
        if self._active or threading.get_ident()!=self._owner: raise TectonicsError('close W08 on its idle owner thread')
        self._closed = True
        try:
            if self._motion is not None: self._motion.close()
            if self._context is not None: self._context.close()
        finally:
            if self._current_guard is not None: self._current_guard.__exit__(None,None,None)
            self._current = None
            if self._guard is not None: self._guard.__exit__(None,None,None)

    def __enter__(self): self._check(); return self
    def __exit__(self,*_): self.close()
