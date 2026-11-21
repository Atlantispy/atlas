"""Chronological W08 finite stocks, exact regime events and atomic restart.

Prescribed affine regional footprints and homogeneous finite material stocks.
Steady wedge temperature is a separate accepted diagnostic, not a transient heat
history. A regime label never supplies missing kinematics or a continental law.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import hashlib
import json
import math
import threading
from time import perf_counter

import numpy as np

from ._validation import TectonicsError, scalar, frozen, _immutable_view, _float_quanta
from . import _w08_history_funding as _history
from .materials import _json, _name
from .constitutive import _cancel
from .geometry import PlanarGeometry
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext, content_record
from .storage import ArrayStore
from .spreading import _within_budget
from .stokes_execution import _native_lease
from .transform import AffineMotionInterval, PreparedAffineMotion
from .w08_inventory import W08Inventory, advance_magmatic, advance_retirement
from .w08_region import W08Region, _regional_view
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
            motion_descriptor = m.descriptor()
            motion = {k:motion_descriptor[k] for k in motion}
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
        record_bytes = _json(record)
        if len(record_bytes) > 131072: raise TectonicsError('regime input metadata exceeds128KiB')
        for k,v in dict(end_time_s=end,regime=regime,source_id=source_id,_record=record_bytes).items():
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
        return self._output_id(_array_id(self.deformation_gradient))

    def _output_id(self, deformation_digest):
        return _hash(content_record(dict(receipt=self.descriptor(),inventory=self.inventory.inventory_id,
                          geometry=[g.geometry_id for g in self.polygons],
                          reference=[g.geometry_id for g in self.reference_polygons],
                          deformation=deformation_digest)))


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
        self._history_enabled = (isinstance(budget, WorkBudget)
                                 and getattr(budget, '_w08_history_qualification', False) is True)
        if self._history_enabled:
            _schedule_decode = _history.Hold(2*_history.GRAPH+_history.PARSE, budget,
                                              category='w08-schedule-decode')
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
        prepared = 2*1024**2+4*initial.nbytes+region.nbytes+sum(len(i._record) for i in intervals)
        if self._history_enabled:
            self._guard = self._history_hold(prepared, 'w08-workflow-prepared')
        else:
            self._guard = self._resource.reserve(prepared, category='w08-workflow-prepared')
            self._guard.__enter__()
        try:
            self._context = ExecutionContext('scipy'); self.execution_id = self._context.identity
            # Validates represented owners before any state is accepted.
            _regional_view(region, initial, region.polygons, initial, None, self._resource, cancel, emit=False)
            # The preparation allowance covers this schedule during affine setup.
            histories, schedule = [], []
            for i in intervals:
                descriptor = d if i is interval else i.descriptor()
                schedule.append(descriptor)
                m = descriptor['motion'] or dict(gradient_s=[[0.,0.],[0.,0.]],velocity_m_s=[0.,0.],anchor_m=[0.,0.])
                histories.append(AffineMotionInterval(i.end_time_s,**m,source_id=i.source_id))
            self._motion = PreparedAffineMotion(region.polygons,tuple(histories),parcel_ids=region.parcel_ids,
                time_s=initial.time_s,source_id=source_id,budget=self._resource,cancel=cancel)
            self._history_binding_funds = self._history_hold(_history.GRAPH, 'w08-history-prepared-binding')
            _binding_scratch = self._history_hold(_history.ENCODE+_history.BODY+_history.PARSE,
                                                   'w08-history-binding-scratch')
            self._binding = dict(schema='atlas.w08-workflow.v1',source_status='WORKING NON-CANON',
                source_id=source_id,initial_id=initial.inventory_id,region_id=region.region_id,
                intervals=schedule,execution=self.execution_id,
                thermodynamics=None if thermodynamics is None else thermodynamics.thermodynamics_id,
                owners=OWNERS,limits=dict(work_bytes=CAP,intervals=256,native_threads=1))
            self.plan_id = _hash(content_record(self._binding))
            self._check(cancel)
        except BaseException:
            # Drop the staged graph before close releases the ordinary preparation lease.
            schedule = descriptor = m = None
            self.close(); raise

    def _history_hold(self, size, category):
        if self._history_enabled:
            return _history.Hold(size, self._resource, category=category)
        return None

    def _retain_workspace(self, size, category):
        if self._history_enabled:
            return _history.retained_context(size, self._resource, category=category)
        return self._resource.reserve(size, category=category)

    def _fund_store(self, caller_holds):
        if self._history_enabled:
            return _history.bind(self.store, '_w08_history_holds', caller_holds)
        return nullcontext()

    def _output_receipt(self, record):
        # Keep the emitted bytes paid if later materialisation or admission fails.
        charge = self._history_hold(_history.BODY+_history.ENCODE, 'w08-history-issued-receipt')
        raw = _json(record)
        if charge is not None:
            charge.resize(64+len(raw))
        return raw, charge

    def _stopped(self, out):
        _descriptor_work = self._history_hold(_history.GRAPH+_history.PARSE, 'w08-history-stop-decode')
        return out.descriptor()['stopped_at_exhaustion']

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

    def _validate(self,out,*,issued_here=False,retirement_heat_present=False):
        _validation_work = self._history_hold(2*_history.GRAPH+_history.PARSE+_history.NUMERIC,
                                               'w08-history-validation')
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
        if not issued_here:
            expected_events = [t['event_id'] for row in self._binding['intervals'][:i+1]
                               if (t := row['transition']) is not None]
            if d['applied_event_ids'] != expected_events:
                raise TectonicsError('event cursor mismatch or replayed transition')
            empty = [name for name,m,old in zip(inv.node_ids,inv.mass_kg,self.initial.mass_kg) if m == 0 and old > 0]
            if d['exhausted_node_ids'] != empty: raise TectonicsError('exhausted source state mismatch')
        self._event_endpoint(i,d)
        if type(d['accepted_intervals']) is not int or not i+1 <= d['accepted_intervals'] <= 256:
            raise TectonicsError('cumulative accepted-interval ceiling exceeded')
        self._validate_history(d,inv,issued_here=issued_here,
                               retirement_heat_present=retirement_heat_present)
        if self._history_enabled:
            del d['transfer_history']
        for j in range(len(inv.component_ids)):
            values = [*inv.component_mass_kg[:,j], *(-self.initial.component_mass_kg[:,j])]
            if abs(math.fsum(values)) > 128*np.finfo(float).eps*math.fsum(map(abs,values)):
                raise TectonicsError('cross-regime component account does not close')
        q = scalar(d['cumulative_external_heat_j'],'booked heat')
        aq = scalar(d['cumulative_absolute_heat_j'],'absolute heat',nonnegative=True)
        values = [*inv.enthalpy_j,*(-self.initial.enthalpy_j),-q]
        if abs(math.fsum(values)) > 128*np.finfo(float).eps*(math.fsum(map(abs,values))+aq):
            raise TectonicsError('cross-regime enthalpy account does not close')
        if not issued_here:
            motion = self._motion.evaluate(inv.time_s)
            if (tuple(g.geometry_id for g in out.polygons) != tuple(g.geometry_id for g in motion.polygons) or
                    tuple(g.geometry_id for g in out.reference_polygons) != tuple(g.geometry_id for g in self.region.polygons) or
                    not np.array_equal(out.deformation_gradient,motion.deformation_gradient)):
                raise TectonicsError('restored current/reference geometry or deformation mismatch')

    def _validate_history(self,record,inventory,*,issued_here=False,retirement_heat_present=False):
        """Reconcile tagged transfers without replaying a physical solver or its flux."""
        history = record['transfer_history']
        i = record['interval_index']
        if type(history) is not list or len(history) != i+1:
            raise TectonicsError('incomplete tagged transfer provenance')
        components = len(self.initial.component_ids)
        node_index = {n:j for j,n in enumerate(self.initial.node_ids)}
        verify_heat_book = not issued_here or retirement_heat_present
        # Issue has a validated parent and the adapter's new receipt; restore checks every row.
        check_payload = not issued_here
        total_steps = 0
        reshaped = bytearray(len(history))
        try:
            dc = de = rates = edges = heat = expected_heat = spec = a = None
            try:
                for j,r in enumerate(history):
                    spec = self._binding['intervals'][j]
                    prior_row = issued_here and j != i
                    if not prior_row:
                        end = record['end_time_s'] if j==i else self.intervals[j].end_time_s
                        start = self.initial.time_s if j==0 else self.intervals[j-1].end_time_s
                        duration = end-start
                        if j==i and record['stopped_at_exhaustion']: duration=r['duration_s']
                    if spec['retirement'] is None and spec['magmatism'] is None:
                        if not prior_row and r is not None:
                            raise TectonicsError('unexpected transfer in kinematic/cessation interval')
                        spec = None
                        if not issued_here: total_steps += 1
                        continue
                    if not prior_row:
                        exact_end = (type(r) is dict and r.get('exhaustion_duration_s') == r.get('duration_s')
                                     and type(r.get('duration_s')) is float and start+r['duration_s'] == end)
                        if (type(r) is not dict or r.get('source_id') != spec['source_id']
                                or (r.get('duration_s') != duration and not exact_end)):
                            raise TectonicsError('transfer event source or duration mismatch')
                    selected = r['selected_node_ids']
                    if spec['retirement'] is not None:
                        a = spec['retirement']
                        if not prior_row:
                            if check_payload:
                                wrong_mapping = (selected != a['selected_node_ids']
                                                 or r['destination_ids'] != a['destination_ids'])
                            else:
                                # The adapter emits the labels from tuple(raw) as a list in the same order.
                                wrong_mapping = (type(a['selected_node_ids']) is not list
                                                 or type(a['destination_ids']) is not list)
                            if wrong_mapping:
                                raise TectonicsError('retirement owner mapping mismatch')
                        if check_payload:
                            dc = np.asarray(r['transferred_component_mass_kg'], float)
                            de = np.asarray(r['transferred_enthalpy_j'], float)
                            if dc.shape != (3, len(selected), components) or de.shape != (3, len(selected)):
                                raise TectonicsError('retirement receipt shape mismatch')
                        if not issued_here: total_steps += 1
                    else:
                        a = spec['magmatism']
                        if not prior_row:
                            if check_payload:
                                wrong_mapping = selected != a['selected_node_ids']
                            else:
                                wrong_mapping = type(a['selected_node_ids']) is not list
                            if wrong_mapping:
                                raise TectonicsError('magma owner mapping mismatch')
                        if check_payload:
                            rates = np.asarray(a['rates_kg_s'], float)
                            edges = [[selected[x], selected[y]] for x, y in zip(*np.nonzero(rates), strict=False)]
                            if r['edge_ids'] != edges:
                                raise TectonicsError('magma edge mapping mismatch')
                            dc = np.asarray(r['transferred_component_mass_kg'], float)
                            edge_count = len(edges)
                            shape = (edge_count, components)
                            if dc.shape != shape:
                                if edge_count:
                                    reshaped[j] = 1
                                dc = dc.reshape(shape)
                            de = np.asarray(r['transferred_enthalpy_j'], float)
                            heat = np.asarray(r['external_heat_j'], float)
                        else:
                            heat = r['external_heat_j']
                            if prior_row and r['edge_ids']:
                                # A validated legacy receipt can be scalar or rectangular at a different rank.
                                dc = r['transferred_component_mass_kg']
                                if (not isinstance(dc, list) or not isinstance(dc[0], list)
                                        or len(dc[0]) != components or isinstance(dc[0][0], list)):
                                    reshaped[j] = 1
                        # A rounded exhaustion endpoint can have a different booked duration.
                        if not prior_row and (check_payload or r['duration_s'] != duration):
                            expected_heat = (np.zeros(len(selected)) if a['heat_w'] is None
                                             else np.asarray(a['heat_w'], float)*duration)
                            if not np.array_equal(heat, expected_heat):
                                raise TectonicsError('external heat receipt mismatch')
                            expected_heat = None
                        if check_payload:
                            if de.shape != (edge_count,):
                                raise TectonicsError('edge heat shape mismatch')
                            iter(heat)  # The existing heat iteration precedes the magma step check.
                        steps = r['kernel']['accepted_intervals']
                        if not prior_row and (type(steps) is not int or not 1 <= steps <= 256):
                            raise TectonicsError('invalid accepted magma steps')
                        if not issued_here: total_steps += steps
                        rates = edges = heat = None
                    if check_payload and (not np.isfinite(dc).all() or np.any(dc<0) or not np.isfinite(de).all()):
                        raise TectonicsError('invalid extensive transfer receipt')
                    dc = de = spec = a = None
            finally:
                # Do not hold conversion tables past the enclosing step/restore lease on failure.
                del dc, de, rates, edges, heat, expected_heat, spec, a

            def flat_word(values, index, length):
                # Earlier magma receipts may use any rectangular C-order reshape.
                while isinstance(values,list):
                    length //= len(values)
                    row,index = divmod(index,length)
                    values = values[row]
                return values

            def transfers(column):
                key = 'transferred_enthalpy_j' if column is None else 'transferred_component_mass_kg'
                for j,r in enumerate(history):
                    if r is None:
                        continue
                    values = r[key]
                    if self.intervals[j].regime == 'subduction':
                        for dest,allocation in zip(r['destination_ids'],values,strict=False):
                            for src,value in zip(r['selected_node_ids'],allocation,strict=False):
                                yield node_index[src],node_index[dest],value if column is None else value[column]
                    else:
                        edges = r['edge_ids']
                        if column is None:
                            words = iter(values)
                        elif reshaped[j]:
                            length = len(edges)*components
                            words = (flat_word(values,k*components+column,length) for k in range(len(edges)))
                        else:
                            words = (row[column] for row in values)
                        for (src,dest),value in zip(edges,words,strict=False):
                            yield node_index[src],node_index[dest],value

            def heat_words():
                for j,r in enumerate(history):
                    if self.intervals[j].regime == 'magmatism':
                        yield from zip(r['selected_node_ids'],r['external_heat_j'],strict=False)

            def reconciles(stock, observed, column):
                # The decoded words were structurally checked above. Keep one column of
                # exact signed and magnitude totals, in units of the smallest binary64.
                signed = [_float_quanta(word) for word in stock]
                magnitude = []
                amount = absolute = final = None
                try:
                    magnitude = [abs(word) for word in signed]
                    for src,dest,word in transfers(column):
                        amount = _float_quanta(word)
                        absolute = abs(amount)
                        signed[src] -= amount
                        signed[dest] += amount
                        magnitude[src] += absolute
                        magnitude[dest] += absolute
                    if column is None:
                        for node,word in heat_words():
                            k = node_index[node]
                            amount = _float_quanta(word)
                            signed[k] += amount
                            magnitude[k] += abs(amount)
                    for k,word in enumerate(observed):
                        final = _float_quanta(word)
                        if (abs(signed[k]-final) << 45) > magnitude[k]+abs(final):
                            return False
                    return True
                finally:
                    signed.clear()
                    magnitude.clear()
                    del amount, absolute, final

            initial = self.initial.component_mass_kg
            current = inventory.component_mass_kg
            if (any(not reconciles(initial[:,k],current[:,k],k) for k in range(components))
                    or not reconciles(self.initial.enthalpy_j,inventory.enthalpy_j,None)
                    or (not issued_here and total_steps != record['accepted_intervals'])
                    or (verify_heat_book and (math.fsum(float(q) for _,q in heat_words()) != record['cumulative_external_heat_j']
                        or math.fsum(abs(float(q)) for _,q in heat_words()) != record['cumulative_absolute_heat_j']))):
                raise TectonicsError('tagged transfer/stock/heat history does not reconcile')
        finally:
            # Release the backing buffer through the shared closure cell, even on refusal.
            reshaped = None

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
        specification_funds = self._history_hold(_history.GRAPH+_history.PARSE, 'w08-history-interval-spec')
        s = self.intervals[index]; spec = self._binding['intervals'][index]
        if specification_funds is not None:
            specification_funds.resize(_history.GRAPH)
        inv = self.initial if parent is None else parent.inventory
        duration = s.end_time_s-inv.time_s
        a = spec['retirement']; m = spec['magmatism']; receipt = None; stopped=False
        # The declared interval end is published as is (shared end-time rule);
        # an exhaustion event ends at its derived start+duration instead.
        def transfer(dt,end=None):
            if a is not None:
                return advance_retirement(inv,tuple(a['selected_node_ids']),tuple(a['destination_ids']),dt,
                    source_id=s.source_id,parameters=a['parameters'],end_time_s=end,
                    budget=self._resource,cancel=cancel)
            return advance_magmatic(inv,tuple(m['selected_node_ids']),m['rates_kg_s'],dt,
                    source_id=s.source_id,heat_w=m['heat_w'],thermodynamics=self.thermodynamics,
                    context=self._context,end_time_s=end,budget=self._resource,cancel=cancel)
        if a is not None or m is not None:
            adapter_funds = self._history_hold(3*_history.GRAPH+_history.PARSE+_history.ENCODE+
                                               _history.BODY+_history.NUMERIC, 'w08-history-adapter-receipt')
            try: candidate,receipt=transfer(duration,s.end_time_s)
            except (RetirementExhaustionError,MagmaticExhaustionError) as exhausted:
                duration=exhausted.exhaustion_duration_s
                if duration<=0: raise
                # The rejected branch did not spend anything. Compute exactly
                # once up to its declared feasibility event, publish, then stop.
                candidate,receipt=transfer(duration);stopped=True
            if adapter_funds is not None:
                adapter_funds.resize(_history.GRAPH)
            inv=candidate
            # An exhaustion whose derived end start+duration rounds onto the
            # declared end completes the interval, exactly as an exhaustion whose
            # duration equals end-start does; the schedule continues from there.
            if stopped and inv.time_s == s.end_time_s: stopped=False
        else:
            inv = inv.retime(s.end_time_s,source_id=s.source_id,budget=self._resource,cancel=cancel)
        motion = self._motion.evaluate(inv.time_s,cancel=cancel)
        view = self.region.regional_view(inv,motion.polygons,reference_inventory=self.initial,
                                       budget=self._resource,cancel=cancel)
        _assembly_funds = self._history_hold(3*_history.GRAPH+_history.PARSE+_history.ENCODE+
                                             _history.BODY+_history.NUMERIC, 'w08-history-assembly')
        prior = None if parent is None else parent.descriptor()
        history = ([] if prior is None else prior['transfer_history'])+[receipt]
        heat_entries = []
        retirement_heat_present = False
        for j, row in enumerate(history):
            if row is None:
                continue
            heat = row['external_heat_j']
            heat_entries.extend(heat)
            # A restored retirement receipt can carry heat that affects the issued book.
            if heat and self.intervals[j].regime == 'subduction':
                retirement_heat_present = True
        steps = 1 if m is None else receipt['kernel']['accepted_intervals']
        accepted = (0 if prior is None else prior['accepted_intervals'])+steps
        if accepted > 256: raise TectonicsError('joined history exceeds256 accepted intervals')
        record = dict(schema='atlas.w08-output.v1',source_status='WORKING NON-CANON',
            plan_id=self.plan_id,execution=self.execution_id,owners=OWNERS,
            interval_index=index,phase='complete',regime=s.regime,
            start_time_s=self.initial.time_s if index==0 else self.intervals[index-1].end_time_s,
            end_time_s=inv.time_s,stopped_at_exhaustion=stopped,parent_output_id=None if parent is None else parent.output_id,
            applied_event_ids=[t['event_id'] for row in self._binding['intervals'][:index+1]
                               if (t := row['transition']) is not None],
            exhausted_node_ids=[n for n,m,old in zip(inv.node_ids,inv.mass_kg,self.initial.mass_kg) if m==0 and old>0],
            cumulative_external_heat_j=math.fsum(heat_entries),
            cumulative_absolute_heat_j=math.fsum(map(abs,heat_entries)),
            accepted_intervals=accepted,transfer_history=history)
        raw, receipt_funds = self._output_receipt(record)
        if len(raw) > 512*1024: raise TectonicsError('bounded tagged event history exceeds512KiB')
        out = W08Output(inv,motion.polygons,self.region.polygons,frozen(motion.deformation_gradient),view,
                         index,self.checkpoint_id(index),raw)
        if receipt_funds is not None:
            object.__setattr__(out,'_issued_receipt_funds',receipt_funds)
        return out, retirement_heat_present

    def _pack(self,out):
        funds = self._history_hold(2*_history.GRAPH+_history.PARSE+_history.ENCODE+
                                   _history.BODY+_history.NUMERIC, 'w08-history-packed-header')
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
        packed = dict(header,content_id=_hash(header))
        if funds is not None:
            funds.resize(_history.GRAPH+_history.NUMERIC)
            caller_holds = getattr(self,'_w08_history_pack_holds',None)
            if caller_holds is not None:
                caller_holds.append(funds)
        return arrays,packed

    def _header(self,index,meta,parent,key,parent_key):
        _header_funds = self._history_hold(_history.GRAPH+_history.PARSE+_history.ENCODE+
                                            _history.BODY, 'w08-history-header-verification')
        keys = {'schema','plan_id','execution','index','checkpoint_id','parent_checkpoint_id',
                'output_id','inventory','receipt','arrays','content_id'}
        if type(meta) is not dict or set(meta) != keys: raise TectonicsError('invalid W08 checkpoint envelope')
        header = {k:v for k,v in meta.items() if k!='content_id'}
        r = meta['receipt']
        if (meta['schema'] != 'atlas.w08-checkpoint.v1' or meta['plan_id'] != self.plan_id or
                meta['execution'] != self.execution_id or meta['index'] != index or
                meta['checkpoint_id'] != key or meta['content_id'] != _hash(header) or
                meta['parent_checkpoint_id'] != parent_key or
                type(r) is not dict or r.get('parent_output_id') != parent or
                r.get('phase') != 'complete' or r.get('interval_index') != index or
                r.get('owners') != OWNERS):
            raise TectonicsError('stale, partial or misbound W08 checkpoint')
        self._event_endpoint(index,r)

    def _scan(self,end,cancel,holds=None):
        latest,meta,parent,gap = -1,None,None,False
        latest_key = parent_key = None
        latest_holds = []
        for i in range(end+1):
            _cancel(cancel)
            candidate_holds = []
            key = self.checkpoint_id(i)
            with self._fund_store(candidate_holds):
                candidate = self.store.metadata(key)
            if candidate is None: gap=True; continue
            if gap: raise TectonicsError('partial W08 checkpoint history has a gap')
            self._header(i,candidate,parent,key,parent_key)
            latest,meta,parent = i,candidate,candidate['output_id']
            latest_key = parent_key = key
            latest_holds = candidate_holds
        if holds is not None:
            holds.extend(latest_holds)
        return latest,meta,latest_key

    def _restore(self,index,meta,cancel,key):
        # Store.get accounts decode work, not the caller-retained arrays after it
        # returns. Keep their known bounded shapes plus regional observation and
        # validation scratch admitted for the whole restore transaction.
        size = (8*self.initial.nbytes+4*self.region.nbytes+2*1024**2+
                32*len(self.region.node_ids)*len(self.region.parcel_ids)*len(self.initial.component_ids))
        with self._retain_workspace(size,'w08-restore-retained-and-scratch') as _restore_funds:
            out = self._restore_payload(index,meta,cancel,key)
            if self._history_enabled:
                self._output_guard(out,restored_reference=True)
            return out

    def _restore_payload(self,index,meta,cancel,key):
        loaded_holds = []
        with self._fund_store(loaded_holds):
            arrays = self.store.get(key,budget=self._resource)
        _restore_conversion = self._history_hold(_history.NUMERIC, 'w08-history-restore-conversion')
        if arrays is None or set(arrays) != set(meta['arrays']):
            raise TectonicsError('corrupt, partial or changed W08 checkpoint arrays')
        verified_deformation = deformation_digest = None
        for k,a in arrays.items():
            digest = _array_id(a)
            if digest != meta['arrays'][k]:
                raise TectonicsError('corrupt, partial or changed W08 checkpoint arrays')
            if k == 'deformation':
                verified_deformation = _immutable_view(a, compact=True)
                deformation_digest = digest
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
        current = tuple(PlanarGeometry.from_wkb(arrays['current_'+str(j)].tobytes(),
            frame_id=self.region.polygons[0].frame_id,budget=self._resource) for j in range(count))
        def reference_parcel(j, issued):
            raw = arrays['reference_'+str(j)].tobytes()
            if raw == issued.wkb:
                return issued
            return PlanarGeometry.from_wkb(raw, frame_id=self.region.frame_id, budget=self._resource)
        reference = tuple(reference_parcel(j, g) for j,g in enumerate(self.region.polygons))
        view = self.region.regional_view(inv,current,reference_inventory=self.initial,
                                        budget=self._resource,cancel=cancel)
        raw, receipt_funds = self._output_receipt(meta['receipt'])
        reuse_digest = verified_deformation is not None
        deformation = verified_deformation if reuse_digest else arrays['deformation']
        out = W08Output(inv,current,reference,frozen(deformation),view,index,
                        key,raw)
        if receipt_funds is not None:
            object.__setattr__(out,'_issued_receipt_funds',receipt_funds)
        del a, verified_deformation, deformation, arrays, loaded_holds
        _identity_funds = self._history_hold(_history.GRAPH+_history.PARSE+_history.ENCODE+
                                            _history.BODY, 'w08-history-restored-identity')
        output_id = out._output_id(deformation_digest) if reuse_digest else out.output_id
        if output_id != meta['output_id']: raise TectonicsError('checkpoint scientific state identity mismatch')
        del _identity_funds
        self._validate(out); self._stats['restored_outputs'] += 1
        return out

    def _output_guard(self,out,*,restored_reference=False):
        if self._history_enabled:
            guard = getattr(out,'_history_output_funds',None)
            if guard is not None:
                return guard
        size = (4*out.inventory.nbytes+out.deformation_gradient.nbytes+len(out._receipt)+
                sum(g.retained_bytes for g in out.polygons)+getattr(out.regional,'nbytes',0)+65536)
        if self._history_enabled:
            if restored_reference:
                # A restored output can retain its references after the plan is released.
                size += sum(g.retained_bytes for g in out.reference_polygons)
            guard = self._history_hold(size,'w08-latest-output')
            object.__setattr__(out,'_history_output_funds',guard)
            if hasattr(out,'_issued_receipt_funds'):
                object.__delattr__(out,'_issued_receipt_funds')
            return guard
        guard = self._resource.reserve(size,category='w08-latest-output'); guard.__enter__()
        return guard

    def _adopt(self,out,guard=None):
        if guard is None: guard=self._output_guard(out)
        old = self._current_guard
        self._current,self._current_guard = out,guard
        if old is not None and not self._history_enabled: old.__exit__(None,None,None)

    def load(self,index,*,checkpoint_id=None,cancel=None):
        self._index(index)
        with self._operation(cancel):
            # Explicit foreign checkpoint IDs must refuse, never be re-labelled
            # a cache miss after code, parameters or runtime change.
            if checkpoint_id is not None and checkpoint_id != self.checkpoint_id(index):
                raise TectonicsError('explicit checkpoint belongs to stale/different sources or runtime')
            if self.store is None:
                return self._current if self._current and self._current.interval_index==index else None
            meta_holds = []
            last,meta,key = self._scan(index,cancel,meta_holds)
            if last != index: return None
            out = self._restore(index,meta,cancel,key)
            del meta, meta_holds
            self._adopt(out); return out

    def run(self,*,through=None,cancel=None):
        end = len(self.intervals)-1 if through is None else self._index(through)
        with self._operation(cancel):
            current = self._current
            if current is not None and current.interval_index==end and self.store is None:
                if self._stopped(current): raise W08ExhaustionError(current)
                self._stats['latest_hits'] += 1; return current
            if self.store is not None:
                meta_holds = []
                last,meta,key = self._scan(end,cancel,meta_holds)
                current = None if last<0 else self._restore(last,meta,cancel,key)
                del meta, meta_holds
                if current is not None: self._adopt(current)
            elif current is not None and current.interval_index>end:
                raise TectonicsError('earlier outputs are not retained; use an explicit checkpoint store')
            first = 0 if current is None else current.interval_index+1
            if current is not None and self._stopped(current):
                raise W08ExhaustionError(current)
            for index in range(first,end+1):
                self._check(cancel); started = perf_counter()
                with self._retain_workspace(8*self.initial.nbytes+4*1024**2,'w08-step-scratch') as _step_funds:
                    candidate, retirement_heat_present = self._compute(index,current,cancel)
                    pending_guard=self._output_guard(candidate)
                    try:
                        # This exact output carries the receipt and motion just issued by _compute.
                        self._validate(candidate,issued_here=True,
                                       retirement_heat_present=retirement_heat_present)
                        self._stats['physics_seconds'] += perf_counter()-started
                        if self.store is not None:
                            started = perf_counter()
                            pack_holds = []
                            scope = (_history.bind(self,'_w08_history_pack_holds',pack_holds)
                                     if self._history_enabled else nullcontext())
                            with scope:
                                arrays,meta = self._pack(candidate)
                            with self._fund_store(pack_holds):
                                self.store.put(candidate.checkpoint_id,arrays,meta,budget=self._resource,cancel=cancel,
                                               publication_check=lambda:self._check(cancel))
                            del arrays, meta, pack_holds
                            self._stats['storage_seconds'] += perf_counter()-started
                        self._check(cancel); self._adopt(candidate,pending_guard); pending_guard=None
                    finally:
                        if pending_guard is not None and not self._history_enabled:
                            pending_guard.__exit__(None,None,None)
                    self._stats['computed_intervals'] += 1; current = candidate
                    if self._stopped(current): raise W08ExhaustionError(current)
                del _step_funds
            return current

    def close(self):
        if self._closed: return
        if self._active or threading.get_ident()!=self._owner: raise TectonicsError('close W08 on its idle owner thread')
        self._closed = True
        try:
            if self._motion is not None: self._motion.close()
            if self._context is not None: self._context.close()
        finally:
            if self._current_guard is not None and not self._history_enabled:
                self._current_guard.__exit__(None,None,None)
            self._current = None
            self._current_guard = None
            if self._guard is not None and not self._history_enabled:
                self._guard.__exit__(None,None,None)

    def __enter__(self): self._check(); return self
    def __exit__(self,*_): self.close()
