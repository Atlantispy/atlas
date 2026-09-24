"""Bounded execution of independent kernel batches, never independent time steps.

Optimised scalar/batched kernels remain the implementation. Auto uses a small
serial path and a persistent thread pool only for eligible larger batches. A
spawn-process comparison path is explicit: processes are not automatically faster.
No GPU, distributed spatial solver, persistent task queue or production graph.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, CancelledError
from dataclasses import dataclass, field
import multiprocessing
import os
import threading
from typing import Iterable

import numpy as np

from ._validation import snapshot, frozen, input_shape, TectonicsError
from .parameters import ThermalParameters
from .kinematics import Rotation
from .flexure import PeriodicFlexure
from .thermal import half_space_temperature, cooling_work_bytes
from .regional import (advect_regional, regional_work_bytes, pack_regional_result,
                       unpack_regional_result, _validate_definition)
from ._validation import scalar
from .materials import (MaterialState, advect_materials, material_work_bytes,
                        validate_material_result, _definition as _material_definition)
from .resources import WorkBudget, MemoryLimitError, elements, select_budget


def _default_workers():
    return min(2, getattr(os,"process_cpu_count",os.cpu_count)() or 1)


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    mode: str = "auto"
    max_workers: int = field(default_factory=_default_workers)
    max_inflight: int = 4
    max_work_bytes: int = 256 * 1024**2
    inner_threads: int = 1
    min_parallel_elements: int = 262_144
    # Measured in the combined acceptance workload; an allowance, not a worker RSS cap.
    process_baseline_bytes: int = 96 * 1024**2

    def __post_init__(self):
        if self.mode not in ("auto", "serial", "threads", "processes"):
            raise TectonicsError("execution mode must be auto/serial/threads/processes")
        for name in ("max_workers", "max_inflight", "max_work_bytes", "inner_threads",
                     "min_parallel_elements", "process_baseline_bytes"):
            if type(getattr(self,name)) is not int or getattr(self,name) < 1:
                raise TectonicsError(name+" must be a positive integer")
        if self.max_workers > 32 or self.max_inflight > 128:
            raise TectonicsError("bounded local executor supports at most 32 workers/128 in-flight jobs")
        available = getattr(os,"process_cpu_count",os.cpu_count)() or 1
        if self.max_workers*self.inner_threads > available:
            raise TectonicsError("outer/inner thread request exceeds available logical CPUs")


# threadpoolctl limits are PROCESS-wide. Compatible concurrent leases share one
# setting; incompatible/nested changes fail instead of racing to restore limits.
_LIMIT_LOCK = threading.RLock()
_LIMIT_USERS = 0
_LIMIT_VALUE = None
_LIMIT_HANDLE = None
_LIMIT_OWNER = None
_PROCESS_LIMIT_HANDLE = None
_POOL_SLOTS = 0


def _acquire_native_limit(threads):
    global _LIMIT_USERS, _LIMIT_VALUE, _LIMIT_HANDLE, _LIMIT_OWNER
    from threadpoolctl import threadpool_limits
    import scipy.special  # load relevant native libraries before recording limits
    with _LIMIT_LOCK:
        if _LIMIT_USERS and _LIMIT_OWNER != threading.get_ident():
            raise TectonicsError("native thread controls must have one driving Python thread")
        if _LIMIT_USERS and _LIMIT_VALUE != threads:
            raise TectonicsError("conflicting process-wide native thread budgets")
        if not _LIMIT_USERS:
            _LIMIT_HANDLE = threadpool_limits(limits=threads)
            _LIMIT_VALUE = threads
            _LIMIT_OWNER = threading.get_ident()
        _LIMIT_USERS += 1


def _release_native_limit():
    global _LIMIT_USERS, _LIMIT_VALUE, _LIMIT_HANDLE, _LIMIT_OWNER
    with _LIMIT_LOCK:
        _LIMIT_USERS -= 1
        if not _LIMIT_USERS:
            _LIMIT_HANDLE.restore_original_limits()
            _LIMIT_HANDLE = None
            _LIMIT_VALUE = None
            _LIMIT_OWNER = None


def _process_initialise(threads):
    global _PROCESS_LIMIT_HANDLE
    from threadpoolctl import threadpool_limits
    import scipy.special
    _PROCESS_LIMIT_HANDLE = threadpool_limits(limits=threads)


@dataclass(frozen=True, slots=True)
class _AdmittedCall:
    """Internal thread-only adapter to the existing ordered bounded scheduler.

    The caller freezes inputs and owns referenced prepared state. ``run`` receives
    a detached budget whose complete envelope is already reserved by this executor.
    ``accept`` validates the result before the reservation is released. ``abort``
    cooperatively stops sibling calls on failure, then normal draining owns memory
    until running native work finishes. This is not a public arbitrary task queue.
    """
    run: object
    accept: object
    abort: object
    elements: int
    work_bytes: int

    def __post_init__(self):
        if not callable(self.run) or not callable(self.accept) or not callable(self.abort):
            raise TectonicsError('admitted call requires run/accept/abort callbacks')
        if type(self.elements) is not int or self.elements < 1 or type(self.work_bytes) is not int or self.work_bytes < 1:
            raise TectonicsError('admitted call needs positive work and memory bounds')


@dataclass(frozen=True, slots=True)
class _Job:
    kind: str
    parameters: object
    arrays: tuple[np.ndarray, ...]
    backend: str
    work_bytes: int


def _run_job(job: _Job):
    if job.kind == 'admitted':
        return job.parameters.run(WorkBudget(job.work_bytes))
    # A process transfer may restore mutable array backing. Re-establish detached
    # immutable inputs in the receiving process, never trust the pickle flags.
    arrays = tuple(snapshot(a,"worker input") for a in job.arrays)
    budget = WorkBudget(job.work_bytes)
    if job.kind == "cooling":
        out = half_space_temperature(*arrays,job.parameters,backend=job.backend,budget=budget)
    elif job.kind == "rotation":
        out = job.parameters.apply(arrays[0],backend=job.backend,budget=budget)
    elif job.kind == "flexure":
        out = job.parameters.solve(arrays[0],budget=budget)
    elif job.kind == "ale":
        from .remapping import advect_ale
        state,dt,left,right,scheme=job.parameters
        out=advect_ale(state,*arrays,dt,left=left,right=right,scheme=scheme,backend=job.backend,budget=budget)
    elif job.kind == "remap":
        from .remapping import remap_materials
        from .mesh import ColumnGrid1D
        state,scheme=job.parameters
        target=ColumnGrid1D(arrays[0],frame_id=state.grid.frame_id,budget=budget)
        out=remap_materials(state,target,scheme=scheme,backend=job.backend,budget=budget)
    elif job.kind == "materials":
        state, dt, left, right, scheme = job.parameters
        out = advect_materials(state, arrays[0], dt, left=left, right=right,
                              scheme=scheme, backend=job.backend, budget=budget)
    elif job.kind == "regional":
        grid, dt, left, right, scheme = job.parameters
        out = pack_regional_result(advect_regional(*arrays,grid,dt,left=left,right=right,
                                   scheme=scheme,backend=job.backend,budget=budget))
    else:
        raise TectonicsError("unsupported kernel job")
    return out


class _BatchStream:
    """Explicit close also releases an iterator that was never started."""
    def __init__(self, owner, generator):
        self._owner, self._generator = owner, generator

    @property
    def gi_running(self):
        return self._generator.gi_running

    def __iter__(self): return self

    def __next__(self):
        try: return next(self._generator)
        except BaseException:
            self.close()
            raise

    def close(self):
        self._generator.close()
        if self._owner._iterator is self:
            self._owner._active = False
            self._owner._iterator = None


class KernelExecutor:
    """Caller-owned, reusable executor with ordered lazy results and finite queues.

    One active stream per executor. Jobs are independent queries/load scenarios,
    not adjoining spatial tiles or successive evolving states. Retained output
    after yield and native allocator/worker baselines remain caller costs. Running
    native calls are drained on cancellation; cancelling is not killing a kernel.
    """
    def __init__(self, policy: ExecutionPolicy | None = None, *, budget=None):
        policy = ExecutionPolicy() if policy is None else policy
        if not isinstance(policy,ExecutionPolicy):
            raise TectonicsError("typed ExecutionPolicy required")
        self.policy = policy
        self._shared_budget = select_budget(budget)
        self._budget = WorkBudget(policy.max_work_bytes, parent=self._shared_budget)
        self._pool_reservation = None
        self._pool_slots = 0
        self._pool = None
        self._closed = False
        self._entered = False
        self._active = False
        self._iterator = None
        self._cancel = threading.Event()
        self._stats = {"serial_jobs":0,"parallel_jobs":0,"completed_jobs":0,"peak_inflight":0}

    def __enter__(self):
        if self._closed or self._entered:
            raise TectonicsError("executor cannot be re-entered")
        _acquire_native_limit(self.policy.inner_threads)
        self._entered = True
        self._owner_thread = threading.get_ident()
        return self

    def _live(self):
        if self._closed or not self._entered:
            raise TectonicsError("use a live KernelExecutor context")
        if threading.get_ident() != self._owner_thread:
            raise TectonicsError("one driving thread per executor; cancel() is thread-safe")
        if self._cancel.is_set():
            raise CancelledError("executor cancelled")

    def cancel(self):
        self._cancel.set()

    def close(self):
        if self._closed: return
        if self._entered and threading.get_ident() != self._owner_thread:
            raise TectonicsError("close executor on its driving thread after joining consumers")
        self._cancel.set()
        if self._iterator is not None and self._iterator.gi_running:
            raise TectonicsError("join the consuming thread before closing executor")
        try:
            if self._iterator is not None:
                # Normal ownership: caller closes the suspended iterator/executor.
                # A generator executing on another thread cannot be closed safely.
                try:
                    self._iterator.close()
                except ValueError as exc:
                    raise TectonicsError("stop/join the consuming thread before closing executor") from exc
            if self._pool is not None:
                self._pool.shutdown(wait=True,cancel_futures=True)
        finally:
            if self._pool_reservation is not None:
                self._pool_reservation.__exit__(None, None, None)
                self._pool_reservation = None
            if self._pool_slots:
                global _POOL_SLOTS
                with _LIMIT_LOCK:
                    _POOL_SLOTS -= self._pool_slots
                self._pool_slots = 0
            if self._entered:
                _release_native_limit()
                self._entered = False
            self._closed = True

    def __exit__(self,*args):
        self.close()

    def statistics(self):
        return dict(self._stats,reserved_bytes=self._budget.reserved_bytes,
                    peak_reserved_bytes=self._budget.peak_reserved_bytes,
                    mode=self.policy.mode, max_workers=self.policy.max_workers,
                    inner_threads=self.policy.inner_threads,
                    shared_budget=self._shared_budget.statistics(),
                    process_allowance_bytes=(self.policy.process_baseline_bytes * self.policy.max_workers
                                             if self._pool_reservation is not None else 0))

    def temperatures(self, batches: Iterable, parameters: ThermalParameters, *, backend="scipy", cancel=None):
        """batches yields (depth, age) pairs; each pair describes a complete query."""
        if not isinstance(parameters,ThermalParameters):
            raise TectonicsError("explicit ThermalParameters required")
        if backend not in ("scipy","reference"):
            raise TectonicsError("unknown cooling backend")
        return self._stream("cooling",batches,parameters,backend,cancel)

    def rotations(self, batches: Iterable, rotation: Rotation, *, backend="matrix", cancel=None):
        if not isinstance(rotation,Rotation): raise TectonicsError("explicit Rotation required")
        if backend not in ("matrix","reference"): raise TectonicsError("unknown rotation backend")
        return self._stream("rotation",batches,rotation,backend,cancel)

    def flexure(self, batches: Iterable, operator: PeriodicFlexure, *, cancel=None):
        if not isinstance(operator,PeriodicFlexure): raise TectonicsError("explicit PeriodicFlexure required")
        return self._stream("flexure",batches,operator,"fft",cancel)

    def regional_transports(self, batches: Iterable, grid, duration_s, *, left, right,
                            scheme="muscl", backend="numba", cancel=None):
        """Ordered results for independent (H, face-u) queries with one case definition.

        Every item is a complete domain. Adjacent physical tiles and successive
        evolving timesteps must not be submitted as independent jobs.
        """
        _validate_definition(grid,left,right,scheme,backend)
        dt=scalar(duration_s,"duration_s",nonnegative=True)
        return self._stream("regional",batches,(grid,dt,left,right,scheme),backend,cancel)

    def material_transports(self, velocities: Iterable, state: MaterialState, duration_s, *,
                            left, right, scheme="muscl", backend="numba", cancel=None):
        """Independent velocity scenarios for one immutable cohort state.

        Not consecutive timesteps, and not adjoining tiles. All scenarios retain
        the explicitly selected scheme. Auto uses the existing minimum batch-size
        threshold for native cohort jobs; spawn remains an explicit comparison.
        Worker choice never changes accuracy, stage order or shared-face ownership.
        """
        _material_definition(state,left,right,scheme,backend)
        dt=scalar(duration_s,"duration_s",nonnegative=True)
        return self._stream("materials",velocities,(state,dt,left,right,scheme),backend,cancel)

    def ale_transports(self, batches, state, duration_s, *,left,right,scheme="muscl",backend="numba",cancel=None):
        """Independent pairs of physical/mesh velocities; never consecutive states."""
        from .remapping import _mesh_state
        _mesh_state(state)
        if scheme not in ('muscl','upwind') or backend not in ('numba','reference'):raise TectonicsError('invalid ALE scheme/backend')
        dt=scalar(duration_s,'duration',nonnegative=True)
        return self._stream('ale',batches,(state,dt,left,right,scheme),backend,cancel)

    def material_remaps(self, targets, state, *,scheme='linear',backend='numba',cancel=None):
        """Independent target-edge arrays for one immutable source material state."""
        from .remapping import _mesh_state
        _mesh_state(state)
        if scheme not in ('linear','constant') or backend not in ('numba','reference'):raise TectonicsError('invalid remap scheme/backend')
        return self._stream('remap',targets,(state,scheme),backend,cancel)

    def _admitted_calls(self, calls, *, cancel=None):
        """Internal prepared-state jobs: reuse queue, CPU limits and drain policy.

        Shared native indexes and captured closures cannot be sent through spawn.
        The R2 adapter has already chosen its measured serial/parallel route.
        """
        if self.policy.mode == 'processes':
            raise TectonicsError('prepared-state calls support serial/threads, not processes')
        return self._stream('admitted', calls, None, 'native', cancel)

    def _estimate(self,kind,raw,parameters,backend):
        if kind == 'admitted':
            if type(raw) is not _AdmittedCall:
                raise TectonicsError('typed admitted call required')
            return (), (), raw.elements, raw.work_bytes
        if kind == 'ale':
            state,dt,left,right,scheme=parameters;n=state.grid.cells;c=len(state.cohorts)
            if not isinstance(raw,(tuple,list)) or len(raw)!=2:raise TectonicsError('physical/mesh velocity pair required')
            values=tuple(raw);shapes=tuple(input_shape(a) for a in values)
            if shapes!=((n+1,),(n+1,)):raise TectonicsError('N+1 face velocities required')
            return values,shapes,c*n,416*c*n+1088*n+32768*c+32768
        if kind == 'remap':
            state,scheme=parameters;shape=input_shape(raw);ns=state.grid.cells;c=len(state.cohorts)
            if len(shape)!=1 or shape[0]<2:raise TectonicsError('target edges required')
            nt=shape[0]-1
            return (raw,),(shape,),c*nt,160*c*(ns+nt)+576*(ns+nt)+16384*c+32768
        if kind == "materials":
            state,dt,left,right,scheme=parameters
            n=state.grid.cells;c=len(state.cohorts)
            shape=input_shape(raw,"material batch velocities")
            if shape!=(n+1,):raise TectonicsError("material batch needs N+1 velocities")
            size=c*n
            output_bytes=8*c*(2*n+9)
            # Parent payload, IPC capture and returned immutable fields all retain
            # owners until the job is consumed. Same budget governs the worker.
            charge=material_work_bytes(c,n,scheme=scheme)+5*state.nbytes+5*output_bytes+24*(n+1)
            return (raw,),(shape,),size,charge
        if kind == "regional":
            grid,dt,left,right,scheme=parameters
            if not isinstance(raw,(tuple,list)) or len(raw)!=2:
                raise TectonicsError("regional batch requires thickness and face velocities")
            values=tuple(raw);shapes=tuple(input_shape(a) for a in values)
            if shapes != ((grid.cells,),(grid.cells+1,)):
                raise TectonicsError("regional batch needs N thicknesses and N+1 velocities")
            size=grid.cells
            input_bytes=8*(2*size+1);output_bytes=8*(2*size+9)
            charge=regional_work_bytes(size,scheme=scheme)+3*input_bytes+5*output_bytes+8192
            return values,shapes,size,charge
        if kind == "cooling":
            if not isinstance(raw,(tuple,list)) or len(raw)!=2:
                raise TectonicsError("each cooling batch must contain depth and age")
            values = tuple(raw)
            shapes = tuple(input_shape(a) for a in values)
            shape = np.broadcast_shapes(*shapes)
            workspace = cooling_work_bytes(*shapes)
        else:
            values = (raw,)
            shape = input_shape(raw)
            shapes = (shape,)
            if kind == "rotation":
                if not shape or shape[-1]!=3: raise TectonicsError("rotation positions end in three components")
                count = elements(shape)
                workspace = (128*count if backend=="reference" else
                             32*count + 24*min(count//3,65536) + 8192)
            else:
                if not shape or shape[-1]!=parameters.grid.cells: raise TectonicsError("complete flexure domain required")
                workspace = parameters.work_bytes(shape)
        size = elements(shape)
        if size==0: raise TectonicsError("empty kernel batch")
        input_bytes = 8*sum(elements(s) for s in shapes)
        output_bytes = 8*size
        # Include parent capture, transfer copies, output refreezing and operator
        # setup in workers. Does not claim to cap total native-library/process RSS.
        setup = getattr(parameters,"setup_bytes",0)
        charge = workspace + 3*input_bytes + 3*output_bytes + 8*setup + 8192
        return values,shapes,size,charge

    def _parallel(self,size,kind,backend):
        if self.policy.mode=="serial" or self.policy.max_workers==1: return False
        if self.policy.mode in ("threads","processes"): return True
        # The Python reference cooling loop is GIL-bound. Do not promise thread
        # acceleration for it; explicit spawn mode remains available for comparison.
        # Matrix rotations and the new regional batches did not benefit from
        # outer threading in their bounded end-to-end comparisons. Keep their
        # compiled serial path under auto; explicit modes remain testable.
        return (kind not in ("rotation", "regional") and size>=self.policy.min_parallel_elements
                and not(kind in ("cooling","regional","materials","ale","remap") and backend=="reference"))

    def _submit(self,job):
        # threadpoolctl has backend/thread-local limitations. The default keeps
        # BLAS rotations on the driving thread. Explicit threaded matrix runs are
        # accepted only for the tested process-wide OpenBLAS pthread control.
        if job.kind == "rotation" and job.backend == "matrix" and self.policy.mode != "processes":
            from threadpoolctl import threadpool_info
            blas = [x for x in threadpool_info() if x["user_api"] == "blas"]
            if not blas or any(x["internal_api"] != "openblas" or x.get("threading_layer") != "pthreads"
                               or x["num_threads"] != self.policy.inner_threads for x in blas):
                raise TectonicsError("threaded matrix backend not verified; use serial or spawn mode explicitly")
        if self._pool is None:
            # Independent executors must not each assume exclusive use of the CPU.
            # Claim actual pool capacity once, until shutdown has drained its jobs.
            global _POOL_SLOTS
            slots = self.policy.max_workers * self.policy.inner_threads
            with _LIMIT_LOCK:
                available = getattr(os, "process_cpu_count", os.cpu_count)() or 1
                if _POOL_SLOTS + slots > available:
                    raise TectonicsError("combined executor pools exceed available CPU slots")
                _POOL_SLOTS += slots
                self._pool_slots = slots
            try:
                if self.policy.mode == "processes":
                    reservation = self._shared_budget.reserve(
                        self.policy.process_baseline_bytes * self.policy.max_workers,
                        category="process-baseline")
                    reservation.__enter__()
                    self._pool_reservation = reservation
                    self._pool = ProcessPoolExecutor(max_workers=self.policy.max_workers,
                        mp_context=multiprocessing.get_context("spawn"),
                        initializer=_process_initialise,initargs=(self.policy.inner_threads,))
                else:
                    self._pool = ThreadPoolExecutor(max_workers=self.policy.max_workers,
                                                   thread_name_prefix="atlas-kernel")
            except BaseException:
                if self._pool_reservation is not None:
                    self._pool_reservation.__exit__(None, None, None)
                    self._pool_reservation = None
                with _LIMIT_LOCK:
                    _POOL_SLOTS -= self._pool_slots
                self._pool_slots = 0
                raise
        return self._pool.submit(_run_job,job)

    def _stream(self,kind,batches,parameters,backend,cancel):
        self._live()
        if self._active: raise TectonicsError("one active batch stream per executor")
        self._active=True
        def run():
            pending=deque()
            source=None
            lookahead=None
            ended=False
            try:
                self._live()
                source=iter(batches)
                while not ended or lookahead is not None or pending:
                    self._live()
                    if cancel is not None and cancel.is_set(): raise CancelledError("batch stream cancelled")
                    while not ended and len(pending)<self.policy.max_inflight:
                        self._live()
                        if cancel is not None and cancel.is_set():
                            raise CancelledError("batch stream cancelled")
                        if lookahead is None:
                            try: raw=next(source)
                            except StopIteration:
                                ended=True;break
                            estimate=self._estimate(kind,raw,parameters,backend)
                            lookahead=(raw,estimate)
                        raw,(values,shapes,size,charge)=lookahead
                        if charge>self.policy.max_work_bytes:
                            raise MemoryLimitError("single kernel batch exceeds executor envelope")
                        if charge > self._budget.available_bytes and pending:
                            break
                        # No pending work means nobody here can free a reservation:
                        # refuse instead of spinning while a store owns the memory.
                        reservation=self._budget.reserve(charge, category="executor-inflight")
                        try:
                            reservation.__enter__()
                        except MemoryLimitError:
                            if pending:
                                break
                            raise
                        try:
                            captured=tuple(snapshot(a,"submitted input") for a in values)
                            if tuple(a.shape for a in captured)!=shapes:
                                raise TectonicsError("input metadata changed during capture")
                            job=_Job(kind,raw if kind == "admitted" else parameters,captured,backend,charge)
                            checks=raw if kind == "admitted" else None
                            if kind in ('ale','remap'):
                                from .mesh import ColumnGrid1D
                                from .materials import _hash_array
                                if kind=='ale':
                                    state,dt,_,_,scheme=parameters
                                    target=ColumnGrid1D(state.grid.edges_m+dt*captured[1],frame_id=state.grid.frame_id)
                                    checks=(target.grid_id,_hash_array(captured[0]),_hash_array(captured[1]))
                                else:
                                    state,scheme=parameters
                                    target=ColumnGrid1D(captured[0],frame_id=state.grid.frame_id)
                                    checks=(target.grid_id,)
                            if self._parallel(size,kind,backend):
                                value=self._submit(job);parallel=True
                                self._stats["parallel_jobs"]+=1
                            else:
                                value=_run_job(job);parallel=False
                                self._stats["serial_jobs"]+=1
                            pending.append((parallel,value,reservation,checks))
                        except BaseException:
                            reservation.__exit__(None,None,None);raise
                        lookahead=None
                        del raw,values,captured,job
                        self._stats["peak_inflight"]=max(self._stats["peak_inflight"],len(pending))
                        # The serial small-job route stays genuinely lazy.
                        if not parallel: break
                    if not pending:
                        if ended: break
                        continue
                    parallel,value,reservation,checks=pending[0]
                    try:
                        result=value.result() if parallel else value
                        self._live()
                        if cancel is not None and cancel.is_set(): raise CancelledError("batch stream cancelled")
                        if kind == "admitted":
                            result = checks.accept(result)
                        elif kind == "ale":
                            from .materials import MaterialTransportResult
                            state,dt,left,right,scheme=parameters
                            # Submitted velocities are identified in the returned receipt;
                            # immutable state restoration and account/shape checks occur below.
                            if (type(result) is not MaterialTransportResult or
                                result.state.parent_state_id!=state.state_id or result.state.time_s!=state.time_s+dt or
                                result.state.grid.grid_id!=checks[0] or result.state.cohorts!=state.cohorts or result.state.epoch_id!=state.epoch_id or
                                result.scheme!=scheme or result.backend!=backend or type(result._flux) is not bytes or type(result._accounts) is not bytes):
                                raise TectonicsError('ALE worker changed parent/time/method/ownership')
                            receipt=result.state.transition_record
                            if (receipt.get('physical_velocity')!=checks[1] or receipt.get('mesh_velocity')!=checks[2]
                                    or receipt.get('operation')!='ale-cohort-ssprk2-v2' or receipt.get('scheme')!=scheme
                                    or receipt.get('backend')!=backend):raise TectonicsError('ALE worker input identity mismatch')
                            if not np.isfinite(result.face_flux_m2_s).all():raise TectonicsError('nonfinite ALE worker flux')
                            if np.any(result.accounts[:,5]<0) or np.any(result.accounts[:,5]>(.5 if scheme=='muscl' else 1.)):
                                raise TectonicsError('invalid worker admission fraction')
                            from .remapping import _inventories
                            from .materials import _account
                            before=_inventories(state.thickness_m,state.grid,backend);after=_inventories(result.state.thickness_m,result.state.grid,backend)
                            for k in range(len(state.cohorts)):
                                a=result.accounts[k];f=result.face_flux_m2_s[k]
                                expected=_account(before[k],after[k],dt*float(f[0]),-dt*float(f[-1]),float(a[5]))
                                if tuple(a)!=expected:raise TectonicsError('ALE worker conservation mismatch')
                        elif kind == "remap":
                            from .remapping import _inventories
                            from .materials import _account
                            state,scheme=parameters
                            if (type(result) is not MaterialState or result.time_s!=state.time_s or result.cohorts!=state.cohorts or
                                result.epoch_id!=state.epoch_id or result.grid.grid_id!=checks[0]):
                                raise TectonicsError('remap worker changed material history')
                            if result.grid!=state.grid:
                                receipt=result.transition_record
                                if (result.parent_state_id!=state.state_id or receipt.get('operation')!='conservative-remap-v2'
                                        or receipt.get('scheme')!=scheme or receipt.get('backend')!=backend):
                                    raise TectonicsError('remap worker changed lineage/method')
                            before=_inventories(state.thickness_m,state.grid,backend);after=_inventories(result.thickness_m,result.grid,backend)
                            for b,a in zip(before,after):_account(b,a,0.,0.,0.)
                        elif kind == "materials":
                            result=validate_material_result(result,parameters[0],parameters[1])
                            if result.scheme!=parameters[4] or result.backend!=backend:
                                raise TectonicsError("worker changed the selected material method")
                        else:
                            result=frozen(result)  # process output flags cannot be trusted
                        if kind == "regional":
                            result=unpack_regional_result(result,parameters[0].cells,parameters[4],backend)
                    except BaseException:
                        raise
                    pending.popleft()
                    reservation.__exit__(None,None,None)
                    self._stats["completed_jobs"]+=1
                    del value
                    yield result
                    del result
            finally:
                # Retain reservations until running calls really finish.
                if kind == 'admitted':
                    for _, _, _, task in pending:
                        task.abort()
                for parallel,value,_,_checks in pending:
                    if parallel: value.cancel()
                for parallel,value,reservation,_checks in pending:
                    try:
                        if parallel:
                            try: value.result()
                            except BaseException: pass
                    finally: reservation.__exit__(None,None,None)
                pending.clear()
                self._active=False
                self._iterator=None
        iterator=_BatchStream(self,run())
        self._iterator=iterator
        return iterator
