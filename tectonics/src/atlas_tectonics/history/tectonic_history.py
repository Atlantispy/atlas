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


from atlas_tectonics._validation import TectonicsError, scalar
from atlas_tectonics._validation import within_budget
from atlas_tectonics.materials.constitutive import _json
from atlas_tectonics.mechanics.evolving_flexure import (PreparedEvolvingW04Support, W04RigidityState)
from atlas_tectonics.mechanics.evolving_mechanics import (PreparedEvolvingRegionalMechanics,
                                EvolvingMechanicalResult)
from atlas_tectonics.materials.materials import _name
from atlas_tectonics.integration.resources import WorkBudget
from atlas_tectonics.integration.resources import check_event_or_callable
from atlas_tectonics.integration.reuse import ExecutionContext, content_record
from atlas_tectonics.codecs.tectonic_history_codec import (pack_history_result, restore_history_result,
                                     history_result_id, history_result_nbytes, history_restore_bytes)
from atlas_tectonics.subduction.underthrust import PreparedUnderthrust, UnderthrustState
from atlas_tectonics.integration.workflows.drained_column_workflow import W03ColumnState
from atlas_tectonics.integration.workflows.prescribed_support_workflow import W04SurfaceInputs, W04ExteriorLoads


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
    A checkpoint is published only when the budget could also restore it: its
    complete restoration envelope is admitted, while this run still holds the
    new result and its predecessor, before the store write. The live latest
    output is reused, not decoded again, when it is the stored latest and the
    store's change token still matches its verified or published snapshot.
    """
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, prepared, inputs, *, source_id, store=None, cancel=None):
        check_event_or_callable(cancel, 'constitutive work cancelled'); _name(source_id, 'tectonic history source')
        self.prepared, self.inputs, self.store = prepared, inputs, store
        self._owner = threading.get_ident(); self._active = self._closed = False
        self._guard = self._current_guard = self._context = self._current = None
        self._current_store_token = None
        self._stats = dict(computed_outputs=0, restored_outputs=0, latest_hits=0,
                           physics_seconds=0., storage_seconds=0.)
        if type(prepared) is PreparedUnderthrust:
            self.route = 'underthrust-section'
            self.inputs = tuple(scalar(t, 'output time') for t in inputs)
            times = self.inputs
            budget = prepared._budget
            definition = dict(plan_id=prepared.plan_id)
            records = [dict(time_s=t) for t in times]
            input_bytes = 64*len(times)
        elif type(prepared) is PreparedEvolvingW04Support:
            self.route = 'evolving-elastic-support'
            times = tuple(x.time_s for x in inputs)
            budget = prepared._budget
            definition = dict(plan_id=prepared.plan_id)
            records = [x.descriptor() for x in inputs]
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
        elif type(prepared) is PreparedEvolvingRegionalMechanics:
            self.route = 'evolving-regional-mechanics'
            times = tuple(x.context.time_s for x in inputs)
            budget = prepared._resource
            definition = dict(geometry=json.loads(prepared._geometry),
                              boundary_types=json.loads(prepared._pattern),
                              options=json.loads(prepared._options))
            records = [dict(time_s=t,request_id=x.request_id) for t,x in zip(times,inputs)]
            input_bytes = sum(x.nbytes+65536 for x in inputs)
        else:
            raise TectonicsError('supported typed underthrust/evolving mechanical preparation required')
        self.times = times
        self._resource = WorkBudget(CAP,parent=budget)
        if store is not None:
            within_budget(self._resource,store._budget, 'call budget must descend from the prepared run budget')
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
            self.plan_id = _hash(content_record(binding))
            self._check(cancel)
            self._sealed = True
        except BaseException:
            self.close(); raise

    def _check(self, cancel=None):
        check_event_or_callable(cancel, 'constitutive work cancelled')

    @contextmanager
    def _operation(self,cancel):
        self._check(cancel)
        object.__setattr__(self,'_active',True)
        try: yield
        finally: object.__setattr__(self,'_active',False)

    def _index(self,index):
        return index

    def checkpoint_id(self,index):
        return _hash(dict(plan_id=self.plan_id,index=index))

    def statistics(self): return dict(self._stats,resources=self._resource.statistics())

    def _validate(self,result,index,cancel=None):
        p = self.prepared; expected_time = self.times[index]
        d = result.descriptor()
        if self.route == 'underthrust-section':
            if (type(result) is not UnderthrustState or result.plan_id != p.plan_id or
                    result.time_s != expected_time or
                    d['interface'] != p.interface.descriptor() or d['epoch_id'] != p.epoch_id or
                    d['parcels'] != [x.descriptor() for x in p.parcels] or
                    d['host_space_source_id'] != p.host_space_source_id or
                    result.destination_ids != p.destination_ids):
                raise TectonicsError('underthrust history state/source binding mismatch')
            displacement,work = p._motion(expected_time)
        elif self.route == 'evolving-elastic-support':
            x = self.inputs[index]
        else:
            x = self.inputs[index]
            if (type(result) is not EvolvingMechanicalResult or d['request'] != x.descriptor() or
                    not d['steady_snapshot'] or d['time_advanced'] or d['displacement_added'] or
                                        d['input_blocks'] != [b.descriptor() for b in (x.material,*x.body_forces,x.boundary)] or
                    d['surface_pressure'] != (None if x.surface_pressure is None else x.surface_pressure.descriptor())):
                raise TectonicsError('regional history request/execution/response binding mismatch')
            # Reconcile against real producer inputs. A compensated force sum
            # and a replaced zero top boundary cannot reconstruct per-input
            # byte hashes (including signed zeros) from aggregate output alone.
            # x includes both staggered force fields. This existing envelope
            # covers the aggregate/compare arrays and the same bounded scalar
            # scratch as evaluate; _restore_bytes uses this identical lease.
            with self._resource.reserve(4*x.nbytes+65536,category='tectonic-history-input-reconcile'):
                for name in x.boundary.array_names:
                    (-x.surface_pressure.array('downward') if name=='top_w' and x.surface_pressure is not None
                                else x.boundary.array(name))

    def _compute(self,index,parent,cancel):
        x = self.inputs[index]; p = self.prepared
        if self.route == 'underthrust-section': result = p.evaluate(x,cancel=cancel)
        elif self.route == 'evolving-elastic-support':
            result = p.solve(x.state,x.surface,rigidity=x.rigidity,exterior=x.exterior,cancel=cancel)
        else: result = p.evaluate(x,cancel=cancel)
        key = self.checkpoint_id(index)
        record = dict(schema='atlas.tectonic-history-output.v1',plan_id=self.plan_id,
            route=self.route,execution=self.execution_id,index=index,time_s=self.times[index],
            checkpoint_id=key,result_id=history_result_id(result),
            parent_output_id=None if parent is None else parent.output_id,phase='complete')
        return TectonicHistoryOutput(result,index,self.times[index],key,
                                     _hash(content_record(record)),_json(record))

    def _pack(self,out,cancel):
        arrays,payload = pack_history_result(out.result,budget=self._resource,cancel=cancel)
        header = dict(schema='atlas.tectonic-history-checkpoint.v1',record=out.descriptor(),
            output_id=out.output_id,payload=payload,retained_bytes=history_result_nbytes(out.result))
        meta = dict(header,content_id=_hash(header))
        return arrays,meta

    def _header(self,index,meta,parent):
        pass

    def _scan(self,end,cancel):
        latest,meta,parent,_ = -1,None,None,False
        for i in range(end+1):
            check_event_or_callable(cancel, 'constitutive work cancelled'); candidate = self.store.metadata(self.checkpoint_id(i))
            if candidate is None: continue
            self._header(i,candidate,parent)
            latest,meta,parent = i,candidate,candidate['output_id']
        return latest,meta

    def _restore_bytes(self,index,arrays,meta):
        """Largest reservation _restore(index) adds for this checkpoint, from its packed arrays and envelope.

        Its own 3x retained allowance, then the largest of three phases that never overlap: store.get's read
        workspace with its 2x output envelope, the codec restoration with its child codecs, and the route
        validation (regional input reconciliation).
        """
        total = sum(a.nbytes for a in arrays.values())
        check = 4*self.inputs[index].nbytes+65536 if self.route == 'evolving-regional-mechanics' else 0
        return (3*meta['retained_bytes']+MAX_METADATA+
                max(self.store._read_work_bytes()+2*total,history_restore_bytes(meta['payload']),check))

    def _restore(self,index,meta,cancel):
        # Store.get accounts decoding, not the arrays retained by its caller.
        # _restore_bytes admits this whole envelope before a checkpoint is published; keep the two in step.
        with self._resource.reserve(3*meta['retained_bytes']+MAX_METADATA,
                                    category='tectonic-history-restore'):
            key = self.checkpoint_id(index)
            arrays = self.store.get(key,budget=self._resource)
            result = restore_history_result(arrays,meta['payload'],budget=self._resource,cancel=cancel)
            self._validate(result,index,cancel=cancel)
            out = TectonicHistoryOutput(result,index,self.times[index],key,
                                         meta['output_id'],_json(meta['record']))
            self._check(cancel)
            self._stats['restored_outputs'] += 1
            return out

    def _check_store_token(self,token):
        if self.store.change_token() != token:
            raise TectonicsError('tectonic history store changed during verification; retry')

    def _adopt(self,out,guard=None,*,store_token=None):
        if guard is None:
            guard = self._resource.reserve(history_result_nbytes(out.result)+65536,
                                            category='tectonic-history-latest')
            guard.__enter__()
        old = self._current_guard
        object.__setattr__(self,'_current',out); object.__setattr__(self,'_current_guard',guard)
        object.__setattr__(self,'_current_store_token',store_token)
        if old is not None: old.__exit__(None,None,None)

    def load(self,index,*,checkpoint_id=None,cancel=None):
        with self._operation(cancel):
            if self.store is None:
                return self._current if self._current is not None and self._current.index==index else None
            token = self.store.change_token()
            last,meta = self._scan(index,cancel)
            if last != index:
                self._check_store_token(token)
                return None
            out = self._restore(index,meta,cancel)
            self._check_store_token(token)
            self._adopt(out,store_token=token); return out

    def run(self,*,through=None,cancel=None):
        end = len(self.inputs)-1 if through is None else through
        with self._operation(cancel):
            current = self._current
            if self.store is not None:
                token = self.store.change_token()
                last,meta = self._scan(end,cancel)
                if last >= 0:
                    reuse = (current is not None and current.index == last and
                             current.output_id == meta['output_id'] and self._current_store_token == token)
                    # Matching result IDs do not prove the stored chunks are still intact. A changed token
                    # requires normal restoration; a change during scan/restore refuses before adoption.
                    if not reuse:
                        current = self._restore(last,meta,cancel)
                    self._check_store_token(token)
                    if reuse:
                        self._stats['latest_hits'] += 1
                    else:
                        self._adopt(current,store_token=token)
                elif current is not None:
                    raise TectonicsError('previously committed checkpoint prefix disappeared')
                else:
                    self._check_store_token(token)
            elif current is not None and current.index > end:
                raise TectonicsError('earlier outputs are not retained; use a checkpoint store')
            if current is not None and current.index==end:
                if self.store is None: self._stats['latest_hits'] += 1
                return current
            first = 0 if current is None else current.index+1
            for i in range(first,end+1):
                parent_token = self._current_store_token if self.store is not None and current is not None else None
                if self.store is not None and current is not None:
                    # A writer may commit just after our previous publication, even within this run call.
                    self._check_store_token(parent_token)
                check_event_or_callable(cancel, 'constitutive work cancelled'); started = perf_counter()
                out = self._compute(i,current,cancel)
                self._stats['physics_seconds'] += perf_counter()-started
                guard = self._resource.reserve(history_result_nbytes(out.result)+65536,
                                                category='tectonic-history-latest')
                guard.__enter__()
                try:
                    self._check(cancel)
                    store_token = None
                    if self.store is not None:
                        started = perf_counter(); arrays,meta = self._pack(out,cancel)
                        # An immutable checkpoint that this budget could not restore would block the history
                        # for good (_scan always finds it). Admit its restoration now, holding this result and
                        # its predecessor, more than a fresh-session restore holds; refuse before writing.
                        with self._resource.reserve(self._restore_bytes(i,arrays,meta),
                                                    category='tectonic-history-restore-admission'):
                            pass
                        if parent_token is not None:
                            # Computation and packing release the database; neither may bless an intervening write.
                            self._check_store_token(parent_token)
                        def publication_check():
                            nonlocal store_token
                            self._check(cancel)
                            # put calls this after all inserts, inside its SQLite write transaction. Reading
                            # the token after put returns could bless a different writer's intervening change.
                            token = self.store.change_token()
                            store_token = token
                        self.store.put(out.checkpoint_id,arrays,meta,budget=self._resource,cancel=cancel,
                                       publication_check=publication_check)
                        self._stats['storage_seconds'] += perf_counter()-started
                    self._check(cancel); self._adopt(out,guard,store_token=store_token); guard=None
                    self._stats['computed_outputs'] += 1; current=out
                finally:
                    if guard is not None: guard.__exit__(None,None,None)
            return current

    def close(self):
        if self._closed: return
        object.__setattr__(self,'_closed',True)
        if self._current_guard is not None: self._current_guard.__exit__(None,None,None)
        object.__setattr__(self,'_current',None)
        object.__setattr__(self,'_current_store_token',None)
        if self._context is not None: self._context.close()
        if self._guard is not None: self._guard.__exit__(None,None,None)

    def __enter__(self):
        self._check(); return self

    def __exit__(self,*_): self.close()
