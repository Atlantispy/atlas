"""Dated, exactly restored histories of the supported section/mechanical routes.

The route owns physics; this layer owns chronology, publication and recovery.
It never transfers material between incompatible representations, accumulates
fixed-reference displacements, or integrates steady velocities into motion.
Prepared routes are borrowed, not closed or silently rebuilt by this owner.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import threading
from time import perf_counter

import numpy as np

from ._validation import TectonicsError, scalar
from .constitutive import _cancel, _json
from .evolving_flexure import (PreparedEvolvingW04Support, W04RigidityState,
                              EvolvingW04SupportResult)
from .evolving_mechanics import (PreparedEvolvingRegionalMechanics,
                                RegionalMechanicalRequest, EvolvingMechanicalResult, _sum_forces)
from .materials import _name
from .resources import WorkBudget
from .reuse import ExecutionContext
from .spreading import _within_budget
from .storage import ArrayStore
from .tectonic_history_codec import (pack_history_result, restore_history_result,
                                     history_result_id, history_result_nbytes)
from .underthrust import PreparedUnderthrust, UnderthrustState, ROUND
from .w03_workflow import W03ColumnState
from .w04_workflow import W04SurfaceInputs, W04ExteriorLoads


CAP = 128 << 20
MAX_OUTPUTS = 256
MAX_METADATA = 512 << 10


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class W04HistoryInput:
    """Actual producer state and coincident supplied properties/load locations."""
    state: W03ColumnState
    surface: W04SurfaceInputs
    rigidity: W04RigidityState
    exterior: W04ExteriorLoads | None = None

    def __post_init__(self):
        if (type(self.state) is not W03ColumnState or type(self.surface) is not W04SurfaceInputs
                or type(self.rigidity) is not W04RigidityState
                or self.exterior is not None and type(self.exterior) is not W04ExteriorLoads):
            raise TectonicsError('typed W03/surface/rigidity/exterior history inputs required')
        if (self.surface.state_id != self.state.state_id or
                self.rigidity.state_id != self.state.state_id or
                self.rigidity.time_s != self.state.time_s or
                self.exterior is not None and self.exterior.state_id != self.state.state_id):
            raise TectonicsError('history input parts must belong to the exact same state/time')

    @property
    def time_s(self): return self.state.time_s

    def descriptor(self):
        return dict(time_s=self.time_s, state=self.state.state_id,
                    surface=self.surface.input_id, rigidity=self.rigidity.input_id,
                    exterior=None if self.exterior is None else self.exterior.input_id)


@dataclass(frozen=True, slots=True)
class TectonicHistoryOutput:
    result: object
    index: int
    time_s: float
    checkpoint_id: str
    output_id: str
    _record: bytes = field(repr=False)

    def descriptor(self): return json.loads(self._record)


class PreparedTectonicHistory:
    """One typed route, fixed dated input schedule, atomic accepted prefix.

    Use a common <=128 MiB WorkBudget for the producer and ArrayStore. Only the
    latest result is retained here; inputs are bounded and charged as retained
    data. Historical outputs live in the existing lossless chunk-deduplicated
    store. An earlier requested result can be loaded explicitly, not replayed.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('tectonic history definition is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, prepared, inputs, *, source_id, store=None, cancel=None):
        _cancel(cancel); _name(source_id, 'tectonic history source')
        if type(inputs) is not tuple or not 1 <= len(inputs) <= MAX_OUTPUTS:
            raise TectonicsError('one to 256 complete scheduled inputs required')
        if store is not None and not isinstance(store, ArrayStore):
            raise TectonicsError('ArrayStore required')
        self.prepared, self.inputs, self.store = prepared, inputs, store
        self._owner = threading.get_ident(); self._active = self._closed = False
        self._guard = self._current_guard = self._context = self._current = None
        self._stats = dict(computed_outputs=0, restored_outputs=0, latest_hits=0,
                           physics_seconds=0., storage_seconds=0.)
        if type(prepared) is PreparedUnderthrust:
            self.route = 'underthrust-section'
            self.inputs = tuple(scalar(t, 'output time') for t in inputs)
            times = self.inputs
            if times[0] < prepared.time_s or times[-1] > prepared.histories[-1].end_time_s:
                raise TectonicsError('scheduled output lies outside the supplied motion history')
            budget = prepared._budget
            definition = dict(plan_id=prepared.plan_id)
            records = [dict(time_s=t) for t in times]
            input_bytes = 64*len(times)
        elif type(prepared) is PreparedEvolvingW04Support:
            self.route = 'evolving-elastic-support'
            if any(type(x) is not W04HistoryInput for x in inputs):
                raise TectonicsError('W04HistoryInput schedule required')
            times = tuple(x.time_s for x in inputs)
            budget = prepared._budget
            definition = dict(plan_id=prepared.plan_id)
            records = [x.descriptor() for x in inputs]
            if any(b.state.parent_state_id != a.state.state_id for a,b in zip(inputs,inputs[1:])):
                raise TectonicsError('W04 history must follow consecutive W03 parent states, not independent branches')
            # Includes retained column/compaction payloads and source catalogue
            # allowance. Inputs remain producer-owned, never mutable callbacks.
            input_bytes = sum(16*x.state.material.nbytes+1024*math.prod(x.state.compaction.shape)
                              +len(x.surface._payload)+len(_json(x.state.descriptor()))*4
                              +len(x.rigidity.profile._payload)
                              + (0 if x.exterior is None else len(x.exterior._left)+len(x.exterior._right))
                              +65536 for x in inputs)
            for x in inputs:
                prepared._base._check_current(x.state,x.surface,x.exterior,None,cancel)
                prepared._check_rigidity(x.state,x.rigidity)
                if x.rigidity.profile.grid != prepared._base.operator.grid:
                    raise TectonicsError('history cannot change the reference/halo grid')
        elif type(prepared) is PreparedEvolvingRegionalMechanics:
            self.route = 'evolving-regional-mechanics'
            if any(type(x) is not RegionalMechanicalRequest for x in inputs):
                raise TectonicsError('RegionalMechanicalRequest schedule required')
            times = tuple(x.context.time_s for x in inputs)
            budget = prepared._resource
            definition = dict(geometry=json.loads(prepared._geometry),
                              boundary_types=json.loads(prepared._pattern),
                              options=json.loads(prepared._options))
            records = [dict(time_s=t,request_id=x.request_id) for t,x in zip(times,inputs)]
            input_bytes = sum(x.nbytes+65536 for x in inputs)
            if any(_json(x.context.geometry()) != prepared._geometry or
                   _json(x.boundary.descriptor()['boundary_types']) != prepared._pattern for x in inputs):
                raise TectonicsError('history requires one fixed geometry/epoch/frame/boundary type')
        else:
            raise TectonicsError('supported typed underthrust/evolving mechanical preparation required')
        if any(b <= a for a,b in zip(times,times[1:])):
            raise TectonicsError('history times must strictly increase; no duplicate or reversed instant')
        self.times = times
        self._resource = WorkBudget(CAP,parent=budget)
        if store is not None:
            _within_budget(self._resource,store._budget)
            if store._budget.max_bytes > CAP:
                raise TectonicsError('history store and producer require a common <=128 MiB budget')
        self._guard = self._resource.reserve(input_bytes+2*MAX_METADATA,
                                              category='tectonic-history-inputs')
        self._guard.__enter__()
        try:
            self._context = ExecutionContext('scipy')
            self.execution_id = self._context.identity
            binding = dict(schema='atlas.tectonic-history.v1', source_status='WORKING NON-CANON',
                route=self.route, source_id=source_id, execution=self.execution_id,
                definition=definition, inputs=records, limits=dict(outputs=MAX_OUTPUTS,work_bytes=CAP),
                semantics='route-owned physics; complete dated states; no inferred cross-route conversion')
            self._binding = _json(binding)
            if len(self._binding) > MAX_METADATA:
                raise TectonicsError('history input/source metadata exceeds 512 KiB')
            self.plan_id = _hash(binding)
            self._check(cancel)
            self._sealed = True
        except BaseException:
            self.close(); raise

    def _check(self, cancel=None):
        if self._closed or self._owner != threading.get_ident():
            raise TectonicsError('open history on its owner thread required')
        p = self.prepared
        if p._closed or getattr(p,'_active',False):
            raise TectonicsError('borrowed producer must remain open and idle')
        if getattr(p,'_owner',self._owner) != self._owner:
            raise TectonicsError('history and producer must share an owner thread')
        _cancel(cancel); self._context.verify()
        # Catch a preparation created under older loaded/source bytes even on a
        # restore-only route which would never call its numerical solver.
        old = (p.execution_id if self.route == 'underthrust-section' else
               p._base._context.scipy.identity if self.route == 'evolving-elastic-support' else
               None if p._plan is None else p._plan._context_id)
        if old is not None and old != self.execution_id:
            raise TectonicsError('producer and history execution identities differ')

    @contextmanager
    def _operation(self,cancel):
        self._check(cancel)
        if self._active: raise TectonicsError('reentrant tectonic history execution refused')
        object.__setattr__(self,'_active',True)
        try: yield
        finally: object.__setattr__(self,'_active',False)

    def _index(self,index):
        if type(index) is not int or not 0 <= index < len(self.inputs):
            raise TectonicsError('complete scheduled output index required')
        return index

    def checkpoint_id(self,index):
        return _hash(dict(plan_id=self.plan_id,index=self._index(index)))

    def statistics(self): return dict(self._stats,resources=self._resource.statistics())

    def _validate(self,result,index):
        p = self.prepared; expected_time = self.times[index]
        d = result.descriptor()
        if self.route == 'underthrust-section':
            if (type(result) is not UnderthrustState or result.plan_id != p.plan_id or
                    result.time_s != expected_time or d['execution_id'] != self.execution_id or
                    d['interface'] != p.interface.descriptor() or d['epoch_id'] != p.epoch_id or
                    d['parcels'] != [x.descriptor() for x in p.parcels] or
                    d['host_space_source_id'] != p.host_space_source_id or
                    result.destination_ids != p.destination_ids):
                raise TectonicsError('underthrust history state/source binding mismatch')
            expected = np.frombuffer(p._stock,np.float64).reshape(3,-1)
            fields = (result.volume_m3,result.mass_kg,result.enthalpy_j)
            for values,stock in zip(fields,expected):
                if any(abs(math.fsum(row)-old) > ROUND*abs(old) for row,old in zip(values,stock)):
                    raise TectonicsError('restored finite material/enthalpy account does not close')
            displacement,work = p._motion(expected_time)
            if not np.array_equal(result.displacement_m,displacement) or not np.array_equal(result.boundary_work_j,work):
                raise TectonicsError('restored displacement/work history mismatch')
            potential = np.array([expected[1,j]*p.gravity_m_s2*float(
                g._geom.centroid.y-p.parcels[j].polygon._geom.centroid.y)
                for j,g in enumerate(result.polygons)])
            if not np.array_equal(result.gravitational_change_j,potential):
                raise TectonicsError('restored geometry/gravitational account mismatch')
        elif self.route == 'evolving-elastic-support':
            x = self.inputs[index]; base = p._base
            expected = dict(plan_id=p.plan_id,current_state=x.state.state_id,
                current_surface=x.surface.input_id,current_rigidity=x.rigidity.input_id,
                current_exterior=None if x.exterior is None else x.exterior.input_id,
                time_s=expected_time,reference_state=base.reference.state_id,
                reference_surface=base.reference_surface.input_id,
                reference_rigidity=p.reference_rigidity.input_id,
                absolute_reference_load=p.reference_absolute_load.input_id,
                execution_id=base._context.identity,vertical_response_owner='W04',
                total_reference_result=True,feedback_applied=False)
            if (type(result) is not EvolvingW04SupportResult or any(d.get(k)!=v for k,v in expected.items()) or
                    result.values.shape != (x.state.material.grid.cells,8) or
                    not np.array_equal(result.absolute_values[:,0],p.reference_absolute_load.downward_pressure_pa)):
                raise TectonicsError('elastic history input/reference/response binding mismatch')
        else:
            x = self.inputs[index]
            if (type(result) is not EvolvingMechanicalResult or d['request'] != x.descriptor() or
                    not d['steady_snapshot'] or d['time_advanced'] or d['displacement_added'] or
                    result.mechanics.descriptor()['context_id'] != self.execution_id or
                    d['input_blocks'] != [b.descriptor() for b in (x.material,*x.body_forces,x.boundary)] or
                    d['surface_pressure'] != (None if x.surface_pressure is None else x.surface_pressure.descriptor())):
                raise TectonicsError('regional history request/execution/response binding mismatch')
            definition = result.mechanics.descriptor()['definition']
            options = json.loads(p._options)
            if any(definition.get(k)!=v for k,v in options.items()):
                raise TectonicsError('regional history solver/reference convention mismatch')
            # Reconcile against real producer inputs. A compensated force sum
            # and a replaced zero top boundary cannot reconstruct per-input
            # byte hashes (including signed zeros) from aggregate output alone.
            with self._resource.reserve(4*x.nbytes+65536,category='tectonic-history-input-reconcile'):
                for axis in ('u','w'):
                    if not np.array_equal(result.array('force_'+axis+'_n_m3'),_sum_forces(x.body_forces,axis)):
                        raise TectonicsError('regional history physical force mismatch')
                for name in x.boundary.array_names:
                    expected = (-x.surface_pressure.array('downward') if name=='top_w' and x.surface_pressure is not None
                                else x.boundary.array(name))
                    if not np.array_equal(result.array('boundary_input_'+name),expected):
                        raise TectonicsError('regional history physical boundary mismatch')

    def _compute(self,index,parent,cancel):
        x = self.inputs[index]; p = self.prepared
        if self.route == 'underthrust-section': result = p.evaluate(x,cancel=cancel)
        elif self.route == 'evolving-elastic-support':
            result = p.solve(x.state,x.surface,rigidity=x.rigidity,exterior=x.exterior,cancel=cancel)
        else: result = p.evaluate(x,cancel=cancel)
        self._validate(result,index)
        record = dict(schema='atlas.tectonic-history-output.v1',plan_id=self.plan_id,
            route=self.route,execution=self.execution_id,index=index,time_s=self.times[index],
            checkpoint_id=self.checkpoint_id(index),result_id=history_result_id(result),
            parent_output_id=None if parent is None else parent.output_id,phase='complete')
        return TectonicHistoryOutput(result,index,self.times[index],self.checkpoint_id(index),
                                     _hash(record),_json(record))

    def _pack(self,out,cancel):
        arrays,payload = pack_history_result(out.result,budget=self._resource,cancel=cancel)
        header = dict(schema='atlas.tectonic-history-checkpoint.v1',record=out.descriptor(),
            output_id=out.output_id,payload=payload,retained_bytes=history_result_nbytes(out.result))
        meta = dict(header,content_id=_hash(header))
        if len(_json(meta)) > MAX_METADATA: raise TectonicsError('history checkpoint metadata exceeds 512 KiB')
        return arrays,meta

    def _header(self,index,meta,parent):
        if type(meta) is not dict or set(meta) != {'schema','record','output_id','payload','retained_bytes','content_id'}:
            raise TectonicsError('invalid tectonic history checkpoint envelope')
        r = meta['record']
        keys = {'schema','plan_id','route','execution','index','time_s','checkpoint_id','result_id','parent_output_id','phase'}
        if type(r) is not dict or set(r) != keys:
            raise TectonicsError('invalid tectonic history output record')
        expected = dict(schema='atlas.tectonic-history-output.v1',plan_id=self.plan_id,
            route=self.route,execution=self.execution_id,index=index,time_s=self.times[index],
            checkpoint_id=self.checkpoint_id(index),parent_output_id=parent,phase='complete')
        if (meta['schema'] != 'atlas.tectonic-history-checkpoint.v1' or
                any(r.get(k)!=v for k,v in expected.items()) or meta['output_id'] != _hash(r) or
                meta['content_id'] != _hash({k:v for k,v in meta.items() if k!='content_id'}) or
                type(meta['retained_bytes']) is not int or not 0 < meta['retained_bytes'] <= CAP):
            raise TectonicsError('stale, partial or misbound tectonic history checkpoint')

    def _scan(self,end,cancel):
        latest,meta,parent,gap = -1,None,None,False
        for i in range(end+1):
            _cancel(cancel); candidate = self.store.metadata(self.checkpoint_id(i))
            if candidate is None: gap=True; continue
            if gap: raise TectonicsError('tectonic checkpoint prefix has a gap')
            self._header(i,candidate,parent)
            latest,meta,parent = i,candidate,candidate['output_id']
        return latest,meta

    def _restore(self,index,meta,cancel):
        # Store.get accounts decoding, not the arrays retained by its caller.
        with self._resource.reserve(3*meta['retained_bytes']+MAX_METADATA,
                                    category='tectonic-history-restore'):
            arrays = self.store.get(self.checkpoint_id(index),budget=self._resource)
            if arrays is None: raise TectonicsError('checkpoint disappeared during restore')
            result = restore_history_result(arrays,meta['payload'],budget=self._resource,cancel=cancel)
            self._validate(result,index)
            if (history_result_id(result) != meta['record']['result_id'] or
                    history_result_nbytes(result) != meta['retained_bytes']):
                raise TectonicsError('restored tectonic result identity/size mismatch')
            out = TectonicHistoryOutput(result,index,self.times[index],self.checkpoint_id(index),
                                         meta['output_id'],_json(meta['record']))
            self._check(cancel)
            self._stats['restored_outputs'] += 1
            return out

    def _adopt(self,out,guard=None):
        if guard is None:
            guard = self._resource.reserve(history_result_nbytes(out.result)+65536,
                                            category='tectonic-history-latest')
            guard.__enter__()
        old = self._current_guard
        object.__setattr__(self,'_current',out); object.__setattr__(self,'_current_guard',guard)
        if old is not None: old.__exit__(None,None,None)

    def load(self,index,*,checkpoint_id=None,cancel=None):
        self._index(index)
        with self._operation(cancel):
            if checkpoint_id is not None and checkpoint_id != self.checkpoint_id(index):
                raise TectonicsError('explicit checkpoint belongs to different source/runtime/inputs')
            if self.store is None:
                return self._current if self._current is not None and self._current.index==index else None
            last,meta = self._scan(index,cancel)
            if last != index: return None
            out = self._restore(index,meta,cancel); self._adopt(out); return out

    def run(self,*,through=None,cancel=None):
        end = len(self.inputs)-1 if through is None else self._index(through)
        with self._operation(cancel):
            current = self._current
            if self.store is not None:
                last,meta = self._scan(end,cancel)
                if last >= 0:
                    current = self._restore(last,meta,cancel); self._adopt(current)
                elif current is not None:
                    raise TectonicsError('previously committed checkpoint prefix disappeared')
            elif current is not None and current.index > end:
                raise TectonicsError('earlier outputs are not retained; use a checkpoint store')
            if current is not None and current.index==end:
                if self.store is None: self._stats['latest_hits'] += 1
                return current
            first = 0 if current is None else current.index+1
            for i in range(first,end+1):
                _cancel(cancel); started = perf_counter()
                out = self._compute(i,current,cancel)
                self._stats['physics_seconds'] += perf_counter()-started
                guard = self._resource.reserve(history_result_nbytes(out.result)+65536,
                                                category='tectonic-history-latest')
                guard.__enter__()
                try:
                    self._check(cancel)
                    if self.store is not None:
                        started = perf_counter(); arrays,meta = self._pack(out,cancel)
                        self.store.put(out.checkpoint_id,arrays,meta,budget=self._resource,cancel=cancel,
                                       publication_check=lambda:self._check(cancel))
                        self._stats['storage_seconds'] += perf_counter()-started
                    self._check(cancel); self._adopt(out,guard); guard=None
                    self._stats['computed_outputs'] += 1; current=out
                finally:
                    if guard is not None: guard.__exit__(None,None,None)
            return current

    def close(self):
        if self._closed: return
        if self._active or self._owner != threading.get_ident():
            raise TectonicsError('close history on its idle owner thread')
        object.__setattr__(self,'_closed',True)
        if self._current_guard is not None: self._current_guard.__exit__(None,None,None)
        object.__setattr__(self,'_current',None)
        if self._context is not None: self._context.close()
        if self._guard is not None: self._guard.__exit__(None,None,None)

    def __enter__(self):
        self._check(); return self

    def __exit__(self,*_): self.close()
