"""Plan05 r13 additive writer with explicit funded operation ownership.
Scientific launch/acceptance remain separate. Logical reservations are not RSS.
See OWNERSHIP.md for the supported caller and explicit retained-release contract.
"""
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from time import perf_counter, process_time, sleep
import weakref

import numpy as np
import psutil

HERE = Path(__file__).resolve().parent
env_hs = os.environ.get('ATLAS_HS_DIR')
if env_hs:
    HS = Path(env_hs).resolve()
else:
    HS = HERE if HERE.name == 'hs' else (HERE / 'hs' if (HERE / 'hs').is_dir() else HERE)
WORKSPACE = HS.parent
R = (
    WORKSPACE
    / 'fidelity-integration-20261005'
    / 'continuation-repair-20261013'
    / 'optimisation-20261014'
    / 'resumability-r1'
)
C = R / 'compact-geometry-r1'
ENV = WORKSPACE / '.r44-env'
ISSUER = 'private_heat_native_issuer_r13.py'
GIB = 1 << 30
RSS_GUARD, FREE_FLOOR = 12 * GIB, 1 * GIB
WORKERS = 6
INPUT = 'W4 same-call control (C/step7_same_call_heat_control.py)'
WORKER_TAG = 'private_heat_functionals_parallel_r1.py'
CHILD_FLAGS = ('-B', '-s', '-P')
WORKER_LAUNCH = (
    "environment = dict(os.environ, OPENBLAS_NUM_THREADS='1')",
    "command = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker']",
)

D02_ALLOWED_LAYOUT_NAMES = ('lf3', 'lh')
CONTROL_PINS = {
    'lf3': 'e5cef40c1b15a263a74d894252321a5af969ce35b37b9dfcf31aa3b94fd123c6',
    'lh': 'acd34ca42dc6464f4654e518d322d1ee03e1900b8159e0012fc3e6a2b27265d8',
}
STEP7_CONTROL_SHA256 = '91db76106dd18758d9c8b62173793d9ea33e1f35a03873112d8faf21dd7a027a'

D02_CAPTURE_SCHEMA = 'atlas.private.d02-correspondence-capture.r13'
D02_THERMAL_MESH_SCHEMA = 'atlas.private.thermal-mesh-record.r13'
# Withdrawn r11 historical projection, used only by disabled historical helpers.
# Selected r13 launches must use launch_plan05_r13.py and its resource admission.
D02_CAPTURE_OVERHEAD_MIB = 24.0




ARRAY_NAMES = (
    'enthalpy_j',
    'input_capacity_j_k',
    'input_enthalpy_j',
    'input_source_w',
    'temperature_k',
)


class ObserverCaptureError(RuntimeError):
    """Observer failure; retained_owner_id names its explicit funded lifetime."""


class ObserverCleanupError(RuntimeError):
    pass


def _describe_failure(error):
    # No source lookup, arbitrary formatting, frame-local scan or graph mutation.
    args = error.args
    message = args[0] if args and type(args[0]) is str else '<non-text exception arguments>'
    return {'type': type(error).__name__, 'message': message[:4096],
            'diagnostic_truncated': len(message) > 4096}


def _failure_info(error):
    try:
        return _describe_failure(error)
    except BaseException:
        return {'type': type(error).__name__, 'message': '<diagnostic unavailable>',
                'diagnostic_failed': True}


def _annotate_observer_failure(error, owner_id, *, protected=None):
    # Optional attributes never replace the already-selected original failure.
    # With any supplied CONTROL root, do not modify exception objects at all:
    # the raised object may itself be that root or one of its descendants.
    if protected is not None:
        return
    try:
        error.retained_owner_id = owner_id
    except BaseException:
        pass
    try:
        info = _failure_info(error)
        error.observer_failure = info
    except BaseException:
        pass


def _copy_termination(error):
    if isinstance(error, KeyboardInterrupt):
        return KeyboardInterrupt()
    if isinstance(error, SystemExit):
        code = error.code
        return SystemExit(code if type(code) in (str, int, type(None)) else 1)
    return None


RUNTIME_PINS = {
    'atlas_tectonics.resources': ('runtime-src/atlas_tectonics/resources.py',
        'fc81fd874dfe5f5ef9fc7e1f235a0d63f1126973a3e5ae22c6ee6b9dd15ff63c'),
    'atlas_tectonics.integration_spatial_transport':
        ('runtime-src/atlas_tectonics/integration_spatial_transport.py',
         '70cdfc9a5b0a4e6b518f6354550fc2a23b333a0474c07dfac55f670cdffde230'),
    'mesh_tables': ('helpers/mesh_tables.py',
        '5fd2afcde6064fcd004a041d0ecfa4a40da90c84f8b36e9c24df0f011cd897ab'),
    'exterior_mesh_patch': ('helpers/exterior_mesh_patch.py',
        '84367f31a6cb1cc32e8d111fa21f1b21f1dcaa12f82aa94266c00888a6a6d890'),
}

NUMPY_IO_PINS = {
    'lib/_npyio_impl.py': 'f66964e8201c9039c121a396d4ac7278f9cd35482e442136728de59365deb63c',
    'lib/_format_impl.py': 'fd316042dae09dd9105b13d28dd3bde6577f7028044a98ec274e012ea64f18d9',
}


def _bind_observer_runtime(layout):
    """Called only after the existing selected-layout path fence is installed."""
    import importlib
    from types import SimpleNamespace
    if (sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 12)
            or sys.maxsize != (1 << 63)-1):
        raise RuntimeError('Observer container accounting requires selected 64-bit CPython 3.12')
    for relative, expected in NUMPY_IO_PINS.items():
        if _file_sha(Path(np.__file__).resolve().parent / relative) != expected:
            raise RuntimeError('Observer NumPy I/O accounting source differs: '+relative)
    modules = {}
    for name, (relative, expected) in RUNTIME_PINS.items():
        module = importlib.import_module(name)
        source = Path(module.__file__).resolve()
        if source != (layout / relative).resolve() or _file_sha(source) != expected:
            raise RuntimeError('Observer dependency differs from selected layout: ' + name)
        modules[name] = module
    resource = modules['atlas_tectonics.resources']
    mesh = modules['mesh_tables']
    transport = modules['atlas_tectonics.integration_spatial_transport']
    return SimpleNamespace(MemoryLimitError=resource.MemoryLimitError,
        WorkBudget=resource.WorkBudget, ResizableLease=resource._ResizableLease,
        Mesh=mesh.CompactMesh, view=modules['exterior_mesh_patch']._view,
        decode_charge=mesh._decode_charge, dict_bytes=mesh._dict_bytes,
        list_bytes=mesh._list_bytes, json_capacity=transport._json_encoding_capacity)


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb', buffering=0) as stream:
        while True:
            block = stream.read(65536)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _array_payload_sha(array):
    """Hash native C-order bytes without copying, including empty ND arrays."""
    if type(array) is not np.ndarray or not array.flags.c_contiguous:
        raise TypeError('Compact array payload must be a C-contiguous ndarray')
    digest = hashlib.sha256()
    # memoryview.cast rejects some zero-dimensional extents even though their
    # payload is the empty byte string. No view/copy is needed for that case.
    if array.nbytes:
        digest.update(memoryview(array).cast('B'))
    return digest.hexdigest()


# This single-owner observer runs synchronously in one monitored interpreter.
# Register a concrete owner BEFORE native factory calls/decoding/copying. A linked
# list needs no allocating dict insertion or second tracking-list append to commit.
_ACTIVE_ARENAS = None
OBSERVER_CATEGORY = 'observer-d02'


def retained_owner(owner_id):
    node = _ACTIVE_ARENAS
    while node is not None:
        if id(node) == owner_id:
            return node
        node = node.next
    raise KeyError('No live observer owner with this identity')


def release_retained_owner(owner_id, *, aliases_released=False):
    """Caller attests ALL payload/exception/traceback aliases are dropped first.

    No exception death, GC, negative scan, weakref or slot-clearing inference is
    used. The owning caller must join any consumers and drop every saved alias.
    Without that knowledge leave this owner funded until process teardown.
    """
    owner = retained_owner(owner_id)
    if aliases_released is not True:
        raise ObserverCleanupError('Explicit all-alias release attestation required')
    return owner.release(explicit=True)


class _TemporaryCharge:
    # The complete operation pool remains funded through callback finalisation.
    # close only records end of use; no scratch release precedes failure graphs.
    __slots__ = ('arena', 'size', 'closed')

    def __init__(self, arena, size):
        self.arena, self.size, self.closed = arena, size, False

    def close(self):
        self.closed = True


class _ObserverArena:
    """Explicit operation owner; logical reservations are NOT a heap/RSS bound."""

    def __init__(self, runtime, budget, roots=()):
        if type(budget) is not runtime.WorkBudget:
            raise TypeError('Observer requires the selected native WorkBudget')
        self.runtime, self.budget, self.roots = runtime, budget, roots
        self.pool = None
        self.before = None
        self.native_owners = None
        self.owner_capacity = self.owner_count = 0
        self.values = None
        self.failure = self.secondary_failure = None
        self.failure_traceback = self.secondary_traceback = None
        self.failure_local_roots = None
        self.failure_roots_complete = True
        self.failure_snapshot_error = None
        self.unresolved = False
        self.finalised = self.released = False
        self.capture_identity = None
        self.next = None
        self.linked = False

    def start(self):
        global _ACTIVE_ARENAS
        self.next = _ACTIVE_ARENAS
        _ACTIVE_ARENAS = self
        self.linked = True
        self.pool = self.runtime.ResizableLease(self.budget, category=OBSERVER_CATEGORY)
        self.pool.__enter__()
        self.before = self.budget.statistics()
        self.reserve(65536)  # admitted logical control allowance, not measured heap
        self.values = []
        self.failure_local_roots = []

    def reserve(self, count):
        self.pool.resize(self.pool.count + count)

    def temp(self, count):
        self.reserve(count + 128)
        return _TemporaryCharge(self, count)

    def prepare_owners(self, capacity):
        if self.native_owners is not None or type(capacity) is not int or capacity < 0:
            raise ObserverCaptureError('Invalid/repeated native owner capacity')
        self.reserve(256 + 16 * capacity)
        self.native_owners = [None] * capacity
        self.owner_capacity = capacity

    def acquire(self, factory, *args):
        # A vacant slot is admitted BEFORE invoking the native allocating factory.
        if self.native_owners is None or self.owner_count >= self.owner_capacity:
            raise ObserverCaptureError('Native owner capacity exhausted before allocation')
        slot = self.owner_count
        owner = factory(*args)
        self.native_owners[slot] = owner
        self.owner_count = slot + 1
        self._after_owner_registered(owner)  # fault seam; insertion is already durable
        return owner

    def copy_owner(self, factory, *args):
        # This private helper permits no escape of the native owner or value.
        # On failure its frame is retained by the concrete arena; on successful
        # return only separately funded JSON-domain copies survive the window.
        slot = self.owner_count
        owner = self.acquire(factory, *args)
        result = self.copy_json(getattr(owner, 'value', owner))
        owner = None
        if not self.unresolved:
            self.native_owners[slot] = None
        return result

    def _after_owner_registered(self, owner):
        pass

    def retain(self):
        """Declare an escape BEFORE publishing its alias; returns release identity."""
        self.unresolved = True
        return id(self)

    def failed(self, error):
        self.unresolved = True
        if self.failure is None:
            self.failure = error
            self.failure_traceback = error.__traceback__
        else:
            self.secondary_failure = error
            self.secondary_traceback = error.__traceback__
        # Positive retained roots, never a scan authorising release. A consumer
        # may detach or clear the published exception's frames (assertRaises
        # does both). Retain independent local-reference snapshots first.
        try:
            self._retain_failure_locals(error.__traceback__)
        except BaseException as snapshot_error:
            # The original graph remains concrete and funded. If admission or
            # snapshot storage fails, callers MUST preserve owner-owned frames
            # until explicit release; arbitrary destructive mutation is unsafe.
            self.failure_roots_complete = False
            self.failure_snapshot_error = snapshot_error

    def _retain_failure_locals(self, current):
        while current is not None:
            frame = current.tb_frame
            code = frame.f_code
            # CPython CO_OPTIMIZED: module/exec frames have dynamic namespaces,
            # whose storage is not described by lexical local-slot counts.
            # Refuse them before touching f_locals; keep their original frames.
            if not code.co_flags & 0x0001:
                raise ObserverCaptureError('Retained module/exec frame requires intact owner-owned frames')
            slots = code.co_nlocals + len(code.co_cellvars) + len(code.co_freevars)
            # This admission supports pinned ordinary function frames only.
            # It is logical accounting, not a bound on arbitrary dynamic locals
            # or their first materialisation, nor a Python heap bound.
            self.reserve(2 * self.runtime.dict_bytes(slots) + 512)
            frame_locals = frame.f_locals
            if len(frame_locals) > slots:
                raise ObserverCaptureError('Retained dynamic locals require intact owner-owned frames')
            local_roots = dict(frame_locals)
            self.failure_local_roots.append(local_roots)
            current = current.tb_next

    def keep(self, value):
        self.reserve(256)
        self.values.append(value)
        return value

    def decode(self, raw):
        if type(raw) is not bytes:
            raise TypeError('Selected metadata must be immutable bytes')
        self.reserve(self.runtime.decode_charge(raw) + 256)
        return self.keep(json.loads(raw))

    def encode(self, value):
        encoded, workspace = self.runtime.json_capacity(value, self.budget)
        self.reserve(encoded + workspace + 256)
        # Partial encoder errors retain the complete admitted workspace until
        # explicit release of their independently held traceback/payload aliases.
        result = self.keep(_canon_bytes(value))
        # The pinned encoder returned successfully; its private scratch did not
        # escape. Any exception before here keeps the complete charge retained.
        self.pool.resize(self.pool.count - workspace)
        return result

    def copy_json(self, value):
        # Separately admitted immutable encoding AND retained decode. No nested
        # mutable native row/support payload is borrowed by an output dictionary.
        return self.decode(self.encode(value))

    def observation(self):
        stats = self.budget.statistics()
        categories = stats['categories']
        before = self.before or {'reserved_bytes': stats['reserved_bytes'], 'categories': {}}
        return {'owner_id': id(self), 'owner_capacity': self.owner_capacity,
                'owners_acquired': self.owner_count,
                'native_owners_retained': sum(x is not None for x in (self.native_owners or ())),
                'callback_finalised': self.finalised,
                'retained_funding': self.unresolved and not self.released,
                'explicit_release_required': self.unresolved and not self.released,
                'failure_roots_complete': self.failure_roots_complete,
                'preserve_failure_frames_until_release': not self.failure_roots_complete,
                'released': self.released,
                'observer_reserved_bytes': categories.get(OBSERVER_CATEGORY, 0),
                'observer_before_bytes': before['categories'].get(OBSERVER_CATEGORY, 0),
                'native_reserved_bytes': categories.get('compact-mesh-owned', 0),
                'budget_before': before['reserved_bytes'],
                'budget_after': stats['reserved_bytes'],
                'charge_delta': stats['reserved_bytes'] - before['reserved_bytes'],
                'accounting_kind': 'native-logical-reservation-not-heap-bound'}

    def finalise(self):
        self.finalised = True
        if self.unresolved:
            return self.observation()
        return self.release()

    def release(self, *, explicit=False):
        global _ACTIVE_ARENAS
        if not self.finalised:
            raise ObserverCleanupError('Cannot release before callback finalisation')
        if self.unresolved and not explicit:
            raise ObserverCleanupError('Retained observer owner needs explicit release')
        if self.released:
            return self.observation()
        # Caller contract covers aliases. Drop graph roots and copied payloads
        # before native owners, and owners before the observer reservation.
        had_failure = self.failure is not None or self.secondary_failure is not None
        self.failure = self.secondary_failure = self.roots = None
        self.failure_traceback = self.secondary_traceback = None
        self.failure_local_roots = self.failure_snapshot_error = None
        self.values = None
        if had_failure:
            # Explicit release attests that external graph aliases are gone.
            # Reclaim now-unreachable traceback/frame cycles while both native
            # owners and observer pool remain funded; never clear CONTROL frames.
            gc.collect()
        self.native_owners = None
        self.capture_identity = None
        if self.pool is not None:
            self.pool.__exit__(None, None, None)
        self.released = True
        previous, node = None, _ACTIVE_ARENAS
        while node is not self:
            if node is None:
                raise ObserverCleanupError('Observer owner registry corrupted')
            previous, node = node, node.next
        if previous is None:
            _ACTIVE_ARENAS = self.next
        else:
            previous.next = self.next
        self.next = None
        self.linked = False
        return self.observation()


def _run_observer_operation(runtime, budget, operation, arguments, disposition, phase,
                            protected=None, callback_probe=None):
    # Protect CONTROL by never inspecting/mutating its graph. The owner retains
    # supplied roots and the original failure, covering arbitrary shared frames.
    if callback_probe is not None and (type(callback_probe) is not dict or 'arena' not in callback_probe):
        raise TypeError('Callback transfer requires a pre-existing plain dict arena slot')
    arena = _ObserverArena(runtime, budget, arguments)
    failure = observation = None
    transferred = False
    try:
        arena.start()
        if callback_probe is not None:
            callback_probe['arena'] = arena
            transferred = True
        operation(arena, *arguments)
    except BaseException as error:
        arena.failed(error)
        failure = error
        _annotate_observer_failure(failure, id(arena), protected=protected)
    finally:
        arguments = operation = budget = protected = None
        if not transferred:
            try:
                observation = arena.finalise()
            except BaseException as cleanup:
                arena.failed(cleanup)
                _best_effort_secondary(disposition, cleanup, 'operation-finalise')
                if failure is None:
                    failure = cleanup
                    _annotate_observer_failure(failure, id(arena))
    try:
        disposition['operations'].append({'phase': phase, 'release': observation,
            'owner_id': id(arena), 'failed': failure is not None,
            'deferred_to_callback_finally': transferred})
    except BaseException as reporting:
        # Even post-operation reporting is part of the callback lifetime.
        if not arena.released:
            arena.failed(reporting)
        _best_effort_secondary(disposition, reporting, 'operation-observation')
        if failure is None:
            failure = reporting
            if not arena.released:
                _annotate_observer_failure(failure, id(arena))
    if failure is not None:
        raise failure


def _observe_callback_release(probe):
    arena = probe.get('arena')
    if arena is None:
        return {'operation_not_admitted': True}
    # Clear the final callback slot only after an observed completed release or
    # an explicit funded-retention disposition. On failure leave it recoverable.
    result = arena.finalise()
    probe['arena'] = None
    return result


def _capture_structure_charge(runtime, view, call):
    """Extra containers only. Borrowed row/support values keep their native owners."""
    d, l = runtime.dict_bytes, runtime.list_bytes
    cells, faces, arrays = view.cell_count, view.face_count, len(view._arrays)
    owners = 2*cells + faces + 1
    # Logical structural reservations only; per-row detached payload copies
    # receive independent native encoding/decoding admission below.
    result = l(cells) + l(faces)
    result += cells*(d(14)+d(9)+32+113) + faces*(d(10)+32)
    result += l(owners) + 256*owners  # pre-admitted owner slots and control allowance
    result += d(arrays) + 2*l(arrays) + sum(d(4)+l(len(a.shape))+36*len(a.shape)+256 for a in view._arrays.values())
    result += d(5) + 5*(d(4)+l(1)+512)
    result += d(len(call._bindings)) + l(len(view._tables)) + l(len(view._grids))
    # Fixed top-level schema has <40 containers / <400 slots; path/hash/control scratch.
    result += 40*d(16) + 40*l(16) + 3*65536
    return result


def _save_array(arena, directory, result, name, count):
    array = result.array(name)
    if type(array) is not np.ndarray or array.dtype != np.dtype('float64'):
        raise TypeError('Selected heat result requires float64 ndarray fields')
    if array.shape != (count,) or not array.flags.c_contiguous:
        raise AssertionError('Heat field count/order or contiguous vector contract differs')
    # Copy payload + possible writer copy, ndarray/header/file workspace; actual nbytes.
    temporary = arena.temp(2*array.nbytes + 65536)
    np.save(directory / (name+'.npy'), np.array(array, copy=True), allow_pickle=False)
    temporary.close()


def _saved_array_record(arena, directory, result, name, count):
    temporary = arena.temp(3*65536)
    path = directory / (name+'.npy')
    with path.open('rb', buffering=0) as stream:
        version = np.lib.format.read_magic(stream)
        if version != (1, 0):
            raise ValueError('Selected one-dimensional float64 output requires NPY v1')
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=1024)
        if shape != (count,) or fortran or dtype != np.dtype('float64'):
            raise ValueError('Saved field header differs from actual native array')
        digest = hashlib.sha256()
        size = 0
        while True:
            block = stream.read(65536)
            if not block:
                break
            size += len(block)
            digest.update(block)
    native = result.array(name)
    expected = _array_payload_sha(native)
    if size != native.nbytes or digest.hexdigest() != expected:
        raise ValueError('Saved field bytes differ from actual native array')
    answer = {'dtype': str(dtype), 'shape': [count], 'npy_sha256': _file_sha(path),
              'raw_sha256': expected}
    block = native = None
    temporary.close()
    return answer


def _bind_operation(arena, state, weak_refs, result):
    origin = result._origin_objects
    weak_refs['call'] = weakref.ref(result)
    state['call_weakref'] = weak_refs['call']
    weak_refs['mesh'] = weakref.ref(origin[2])


def _legacy_operation(arena, state, directory, result):
    raw = result._snapshot._metadata
    if type(raw) is not bytes:
        raise TypeError('Selected legacy metadata requires bytes')
    # Borrow existing immutable bytes; write_bytes does not manufacture another full copy.
    (directory / 'legacy_metadata.json').write_bytes(raw)
    state['legacy_result_id'] = result.result_id
    state['legacy_sha'] = hashlib.sha256(raw).hexdigest()


def _capture_operation(arena, state, weak_refs, directory, call, result, arm_index, layout, issuer):
    runtime = arena.runtime
    view = runtime.view(call._origin_objects[2])
    if type(view) is not runtime.Mesh or view._scope is not None:
        raise TypeError('CP1 selected CONTROL requires its authenticated unscoped CompactMesh')
    if view._budget is not arena.budget:
        raise TypeError('Observer and selected mesh must use the same native budget')
    arena.reserve(_capture_structure_charge(runtime, view, call))
    arena.prepare_owners(2 * view.cell_count + view.face_count + 1)
    arena.capture_identity = (id(call), id(result))
    if tuple(result.array_names) != ARRAY_NAMES:
        raise AssertionError('Actual array inventory/count/order differs')
    weak_refs['retval'] = weakref.ref(result)
    for name in ARRAY_NAMES:
        _save_array(arena, directory, result, name, view.cell_count)
    arrays = {name: [view.cell_count] for name in ARRAY_NAMES}
    (directory / 'arrays.json').write_bytes(arena.encode(arrays))
    _write_d02_capture(directory, call, result, state['legacy_result_id'], state['legacy_sha'],
                       arm_index, layout, issuer, arena=arena)


def _observer(directory, arm_index=0, layout=None, runtime=None):
    if runtime is None:
        raise TypeError('Observer requires the selected runtime binding')
    directory.mkdir(parents=True, exist_ok=True)
    monitoring = sys.monitoring
    tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
    monitoring.use_tool_id(tool, 'ab_heat_r13 proof observer')
    state = {'call_weakref': None, 'legacy_result_id': None, 'legacy_sha': None}
    weak_refs = {}
    disposition = {'schema': 'atlas.private.observer-disposition.r13',
        'path': 'not-started', 'control_failure': None, 'operations': [],
        'secondary_failures': [], 'observer_stopped': False,
        'callback_releases': {}, 'callback_slots': {}}

    def stop():
        state.clear()
        failed = False
        termination = None
        for action in (lambda: monitoring.set_events(tool, 0),
                       lambda: monitoring.register_callback(tool, monitoring.events.PY_RETURN, None),
                       lambda: monitoring.free_tool_id(tool)):
            try:
                action()
            except BaseException as error:
                failed = True
                _best_effort_secondary(disposition, error, 'monitoring-cleanup')
                if termination is None:
                    termination = _copy_termination(error)
        disposition['observer_stopped'] = not failed
        # Supplementary only: never used as payload-lifetime/release evidence.
        disposition['supplementary_weakrefs'] = {
            'missing': sorted({'call', 'mesh', 'retval'}-set(weak_refs)),
            'observed_dead': {name: ref() is None for name, ref in weak_refs.items()}}
        if failed:
            if termination is not None:
                raise termination from None
            raise ObserverCleanupError('Observer monitoring cleanup failed')

    def on_return(code, offset, retval):
        if code.co_name not in ('bind_owner_call', 'advance_legacy_packaging', 'advance') or Path(code.co_filename).name != ISSUER:
            return monitoring.DISABLE
        phase = code.co_name
        call = arguments = budget = operation = getter = None
        release_probe = {'arena': None}
        ambient_error = sys.exception()
        primary = None
        try:
            if phase == 'bind_owner_call':
                budget = retval._budget
                operation = _bind_operation
                arguments = (state, weak_refs, retval)
            else:
                getter = state.get('call_weakref')
                call = getter() if getter is not None else None
                if call is None:
                    raise ObserverCaptureError('Missing issued call before capture')
                budget = call._budget
                if phase == 'advance_legacy_packaging':
                    operation = _legacy_operation
                    arguments = (state, directory, retval)
                else:
                    monitoring.set_events(tool, 0)
                    operation = _capture_operation
                    arguments = (state, weak_refs, directory, call, retval, arm_index, layout, code.co_filename)
            _run_observer_operation(runtime, budget, operation, arguments, disposition, phase,
                                    protected=ambient_error, callback_probe=release_probe)
        except BaseException as error:
            primary = error
        finally:
            arguments = retval = call = budget = ambient_error = operation = getter = None
            if phase == 'advance' or primary is not None:
                state.clear()
            try:
                release_result = _observe_callback_release(release_probe)
                disposition['callback_releases'][phase] = release_result
                disposition['callback_slots'][phase] = True
            except BaseException as cleanup:
                arena = release_probe.get('arena')
                if arena is not None:
                    arena.failed(cleanup)
                _best_effort_secondary(disposition, cleanup, 'callback-finalisation-or-reporting')
                if primary is None:
                    primary = cleanup
                    if arena is not None:
                        _annotate_observer_failure(primary, id(arena))
                arena = None
        if primary is not None:
            raise primary

    try:
        monitoring.register_callback(tool, monitoring.events.PY_RETURN, on_return)
        monitoring.set_events(tool, monitoring.events.PY_RETURN)
    except BaseException:
        try:
            stop()
        except BaseException as cleanup:
            _best_effort_secondary(disposition, cleanup, 'monitoring-setup-rollback')
        raise
    return stop, disposition


def _write_disposition(directory, disposition):
    (directory / 'observer_disposition.json').write_text(
        json.dumps(disposition, indent=2, sort_keys=True), encoding='utf8')


def _report_secondary(disposition, error, step):
    try:
        info = _failure_info(error)
    except BaseException:
        info = {'type': type(error).__name__, 'message': '<diagnostic unavailable>',
                'stack': '', 'diagnostic_failed': True}
    info['step'] = step
    try:
        disposition.setdefault('secondary_failures', []).append(info)
    except BaseException:
        pass
    # A failed file write cannot promise a durable file. Expose the failure on stderr.
    try:
        sys.stderr.write('Observer secondary failure at '+step+': '+str(info.get('type', 'Unknown'))+'\n')
    except BaseException:
        pass


def _best_effort_secondary(disposition, error, step):
    try:
        _report_secondary(disposition, error, step)
    except BaseException:
        try:
            sys.stderr.write('Observer secondary reporting unavailable at '+step+'\n')
        except BaseException:
            pass


def _finish_control(stop, disposition, directory, primary):
    failed = False
    termination = None
    try:
        stop()
    except BaseException as error:
        failed = True
        _best_effort_secondary(disposition, error, 'stop')
        termination = _copy_termination(error)
    try:
        _write_disposition(directory, disposition)
    except BaseException as error:
        failed = True
        _best_effort_secondary(disposition, error, 'write-disposition')
        if termination is None:
            termination = _copy_termination(error)
    if failed and primary is None:
        if termination is not None:
            raise termination from None
        raise ObserverCleanupError('Observer stop/report failed after CONTROL success')


def _control_boundary(invoke, stop, disposition, directory):
    if stop is None:
        return invoke()
    try:
        invoke()
    except BaseException as primary:
        # CONTROL owns this traceback. Do not detach or clear it.
        try:
            disposition['path'] = 'exceptional'
            disposition['control_failure'] = _failure_info(primary)
        except BaseException as reporting:
            _best_effort_secondary(disposition, reporting, 'control-failure-reporting')
        try:
            _finish_control(stop, disposition, directory, primary)
        except BaseException:
            # Last-resort precedence even if secondary diagnostic storage itself fails.
            try:
                sys.stderr.write('Observer cleanup/report incomplete; preserving CONTROL failure\n')
            except BaseException:
                pass
        raise
    else:
        disposition['path'] = 'normal'
        disposition['control_failure'] = None
        _finish_control(stop, disposition, directory, None)


def _capture_input_provenance(arena, call, cells):
    """Read exact transported inputs through the selected native accessors."""
    import private_heat_native_issuer_r13 as issuer
    owner, step = call._origin_objects[:2]
    scope = issuer.HEAT_LEDGER.required_scope((owner,), owner._budget)
    # The existing native accessors retain backing on exceptional exit. Their
    # failed frames remain reachable from arena.failure until explicit release.
    with issuer.LIVE_SPATIAL.record_access(step.graph, scope=scope) as graph:
        with issuer.LIVE_SPATIAL.transport_access(step.result, scope=scope) as transported:
            arena.reserve(65536 + 1024 * (len(graph['cells']) + len(transported['cell_ids'])))
            columns = {cid: i for i, cid in enumerate(transported['cell_ids'])}
            if len(columns) != len(transported['cell_ids']):
                raise ObserverCaptureError('Transport input IDs are not unique')
            volumes = {row['cell_id']: row['end_volume_m3'] for row in graph['cells']}
            result = {}
            for row in cells:
                cid = row['cell_id']
                logical = row['native_cell']['logical_cell_id']
                at = columns[logical]
                volume = volumes[logical]
                enthalpy = transported['exact_stocks']['enthalpy_j'][at]
                arena.reserve(512 + 256 * owner._component_count)
                masses = []
                for component in range(owner._component_count):
                    pair = transported['exact_stocks']['component_mass_kg:' + str(component)][at]
                    masses.append([pair[0], pair[1]])
                result[cid] = arena.copy_json({
                    'graph_end_volume_m3': [volume[0], volume[1]],
                    'transport_exact_enthalpy_j': [enthalpy[0], enthalpy[1]],
                    'transport_exact_component_masses_kg': masses})
            bindings = arena.copy_json({'graph_id': step.graph.geometry_id,
                'state_id': step.result.result_id, 'source_stage_id': step.source.result_id,
                'parent_state_id': step.parent.state_id})
            # No accessor view survives clean context-manager finalisation.
            volumes = columns = volume = enthalpy = pair = transported = graph = None
    return result, bindings


def _save_grid_proof(arena, directory, view, descriptors):
    """Persist only the native integer/rational pools and grid index arrays.

    Grid .q arrays contain pool indices, so their digests cannot establish
    physical equality across a cell permutation. These authenticated native
    arrays let the verifier reconstruct exact coordinates independently.
    """
    names = ['q.pair', 'int.sign', 'int.offset', 'int.bytes']
    names.extend(name + suffix for name in view._grids for suffix in ('.q', '.offset'))
    proof = {}
    for name in names:
        array = view._arrays[name]
        # Pinned NPY writer/header/file scratch is admitted before writing.
        # Native immutable payload remains owned through callback finalisation.
        arena.reserve(2 * array.nbytes + 2 * 65536 + 1024)
        filename = 'compact-grid-' + name + '.npy'
        path = directory / filename
        with path.open('xb') as stream:
            np.save(stream, array, allow_pickle=False)
        proof[name] = dict(descriptors[name], file=filename, file_sha256=_file_sha(path))
    return proof


def _write_d02_capture(directory, call, advance_ret, legacy_result_id, legacy_sha,
                       arm_index=0, layout=None, issuer_filename=None, *, arena):
    """Private owned-frame worker: no uncharged direct/fallback entry point."""
    if (not isinstance(arena, _ObserverArena) or
            arena.capture_identity != (id(call), id(advance_ret))):
        raise TypeError('Capture requires the pre-funded operation for these exact inputs')
    if call is None:
        raise RuntimeError('D02 observer missing call from bind_owner_call')
    if legacy_sha is None:
        raise RuntimeError('D02 observer missing legacy_metadata from advance_legacy_packaging')

    from exterior_mesh_patch import _view

    # Extract mesh from call._origin_objects: (owner, step, mesh, snapshot)
    mesh = call._origin_objects[2]
    compact_view = _view(mesh)
    geometry_id = compact_view.geometry_id
    cell_count = compact_view.cell_count
    face_count = compact_view.face_count

    # Requirement (a): Correct owned-row access on mesh.header()
    header = arena.copy_owner(compact_view.header)
    if not isinstance(header, dict):
        raise TypeError(f'Expected header dict from mesh.header(), got {type(header)}')

    # Physical context preserved from mesh header
    support_id = header.get('support_id')
    funding_id = header.get('funding_id')
    grid_id = header.get('grid_id')
    time_s = header.get('time_s')
    trajectory_id = header.get('trajectory_id')
    endpoint = header.get('endpoint')

    # Context explicitly disposed of from header
    retained_header_keys = {
        'support_id',
        'funding_id',
        'grid_id',
        'time_s',
        'trajectory_id',
        'endpoint',
        'schema',
        'method',
    }
    arena.reserve(2*arena.runtime.list_bytes(len(header)))
    disposed_header_fields = sorted(k for k in header if k not in retained_header_keys)

    # Call snapshot metadata and plan decoding
    call_snapshot_meta = arena.decode(call._snapshot._metadata)
    duration_s = float(call_snapshot_meta.get('duration_s', 0.0))
    plan_dict = arena.decode(call._plan)
    boundary = plan_dict.get('boundary', {})

    # Context explicitly disposed of from call / plan
    arena.reserve(2*arena.runtime.list_bytes(len(plan_dict)))
    disposed_call_plan_fields = sorted(k for k in plan_dict if k != 'boundary')

    # Requirement (d): Record ordered call cell IDs in-process and assert actual array/mesh order and counts
    call_cell_ids = call_snapshot_meta.get('cell_ids', [])
    if not isinstance(call_cell_ids, list):
        raise TypeError(f'Expected list for call_cell_ids, got {type(call_cell_ids)}')
    if len(call_cell_ids) != cell_count:
        raise AssertionError(
            f'In-process call cell_ids count {len(call_cell_ids)} != mesh.cell_count {cell_count}'
        )

    # Item (1) fix: Access cell IDs through verified CompactMesh view
    if any(compact_view.cell_id(i) != call_cell_ids[i] for i in range(cell_count)):
        raise AssertionError('In-process call cell_ids order differs from compact_view.cell_id order')

    # Item (5) fix: Check array axis-0 contracts, 1D vector shapes, and captured counts
    bound_arrays = {name: _saved_array_record(arena, directory, advance_ret, name, cell_count)
                    for name in ARRAY_NAMES}

    # Compact mesh descriptors and identity binding
    arena.reserve(4 * len(compact_view._metadata) + 256)
    metadata_utf8 = arena.keep(compact_view._metadata.decode('utf-8'))
    metadata_digest = hashlib.sha256(compact_view._metadata).hexdigest()
    compact_array_descriptors = {
        k: {
            'dtype': compact_view._arrays[k].dtype.str,
            'shape': list(compact_view._arrays[k].shape),
            'nbytes': compact_view._arrays[k].nbytes,
            'sha256': _array_payload_sha(compact_view._arrays[k]),
        }
        for k in sorted(compact_view._arrays)
    }
    compact_tables = list(compact_view._tables)
    compact_grids = list(compact_view._grids)
    grid_proof_arrays = _save_grid_proof(arena, directory, compact_view, compact_array_descriptors)

    # Item (2) fix: Bind exact LogicalIdentity fields per compact_contracts.py:107–134
    ident = compact_view.identity()
    logical_identity = {
        'record_schema': ident.record_schema,
        'sha256': ident.sha256,
        'canonical_bytes': ident.canonical_bytes,
        'wire': ident.to_wire(),
        'expected_geometry_id': compact_view.geometry_id,
    }

    # Native row windows return only independently funded detached copies.

    cells_out = []
    for i in range(cell_count):
        c = arena.copy_owner(compact_view.cell, i)
        psup = arena.copy_owner(mesh.physical_support, i)
        cid = c['cell_id']
        kind = c.get('kind', 'collar' if 'index' in c else 'exterior')

        if kind == 'collar':
            indep_key = {
                'kind': 'collar',
                'index': c['index'],
                'physical_cell_id': c.get('physical_cell_id'),
                'voxel_id': c.get('physical_support', {}).get('voxel_id'),
            }
        elif kind == 'exterior':
            indep_key = {
                'kind': 'exterior',
                'logical_cell_id': c.get('logical_cell_id'),
                'source_key': c.get('source_key'),
                'voxel_index': c.get('voxel_index'),
                'radial_band': c.get('radial_band'),
                'chart': c.get('chart'),
                'voxel_id': c['physical_support']['voxel_id'],
                'radial_layer_id': c['physical_support']['radial_layer_id'],
                'cone_id': c['physical_support']['cone_id'],
            }
        else:
            indep_key = {'kind': kind, 'cell_id': cid}

        cells_out.append({
            'native_cell': c,
            'row_index': i,
            'cell_id': cid,
            'kind': kind,
            'logical_cell_id': c.get('logical_cell_id'),
            'independent_key': indep_key,
            'independent_key_sha256': hashlib.sha256(arena.encode(indep_key)).hexdigest(),
            'physical_volume_bounds_m3': c.get('physical_volume_bounds_m3'),
            'geometry_volume_max_deviation_m3': c.get('geometry_volume_max_deviation_m3'),
            'volume_m3': c.get('volume_m3'),
            'centroid_m': c.get('centroid_m'),
            'faces': c.get('faces'),
            'physical_support': c.get('physical_support'),
            'resolved_support': psup,
        })

    # Exact native face rows, copied inside admitted owner windows.
    faces_out = []
    for fi in range(face_count):
        f = arena.copy_owner(compact_view.face, fi)
        faces_out.append({
            'native_face': f,
            'face_index': fi,
            'face_id': f['face_id'],
            'kind': f.get('kind'),
            'geometry_kind': f.get('geometry_kind'),
            'centroid_m': f.get('centroid_m'),
            'area_vector_m2': f.get('area_vector_m2'),
            'vertices_m': f.get('vertices_m'),
            'owners': f.get('owners'),
            'cartesian_support': f.get('cartesian_support'),
            'relative_advection': f.get('relative_advection'),
        })

    # Assertions on counts and cell IDs
    if len(cells_out) != cell_count:
        raise AssertionError(f'cells_out count {len(cells_out)} != cell_count {cell_count}')
    if any(row['cell_id'] != call_cell_ids[i] for i, row in enumerate(cells_out)):
        raise AssertionError('cells_out cell_ids order does not match call_cell_ids')

    # Requirement (b) & (c): Bind per-arm loaded-source provenance and layout/control pins
    layout_name = layout.name if layout is not None else None
    layout_control_sha = (
        _file_sha(layout / 'control.json')
        if layout is not None and (layout / 'control.json').is_file()
        else None
    )
    step7_control_sha = (
        _file_sha(C / 'step7_same_call_heat_control.py')
        if (C / 'step7_same_call_heat_control.py').is_file()
        else None
    )
    issuer_sha = (
        _file_sha(issuer_filename)
        if issuer_filename and Path(issuer_filename).is_file()
        else None
    )

    provenance = {
        'arm_index': arm_index,
        'layout_name': layout_name,
        'layout_control_sha256': layout_control_sha,
        'step7_control_sha256': step7_control_sha,
        'issuer_sha256': issuer_sha,
        'private_sources': arena.copy_json(dict(call._bindings)) if hasattr(call, '_bindings') else {},
        'loaded_dependencies': call_snapshot_meta.get('loaded_dependencies'),
        'execution_provenance': arena.copy_json(getattr(call._execution, 'provenance', None)),
        'call_id': call.call_id,
        'plan_id': call_snapshot_meta.get('plan_id'),
        'state_id': call_snapshot_meta.get('state_id'),
        'owner_id': call_snapshot_meta.get('owner_id'),
        'owner_definition_id': call_snapshot_meta.get('owner_definition_id'),
    }
    if _SELECTED_ORDER_REPAIR is not None:
        provenance['order_repair'] = arena.copy_json(_SELECTED_ORDER_REPAIR)

    # Context disposition record
    context_disposition = {
        'preserved': {
            'mesh_geometry_id': geometry_id,
            'mesh_counts': {'cell_count': cell_count, 'face_count': face_count},
            'boundary': boundary,
            'time_s': time_s,
            'duration_s': duration_s,
            'grid_id': grid_id,
            'support_id': support_id,
            'funding_id': funding_id,
            'trajectory_id': trajectory_id,
            'endpoint': endpoint,
            'ordered_cell_ids_observed_in_process': True,
            'compact_metadata_digest': metadata_digest,
            'compact_array_descriptors_count': len(compact_array_descriptors),
        },
        'disposed': {
            'header_fields': disposed_header_fields,
            'call_plan_fields': disposed_call_plan_fields,
            'raw_lookup_permutations': ['c.lookup', 'f.lookup'],
            'unexpanded_legacy_record': True,
        },
    }

    input_provenance, input_bindings = _capture_input_provenance(arena, call, cells_out)
    for row in cells_out:
        row['input_provenance'] = input_provenance[row['cell_id']]
    mesh_record = {
        'schema': D02_THERMAL_MESH_SCHEMA,
        'geometry_id': geometry_id,
        'funding_id': funding_id,
        'support_id': support_id,
        'grid_id': grid_id,
        'time_s': time_s,
        'duration_s': duration_s,
        'cell_count': cell_count,
        'face_count': face_count,
        'cells': cells_out,
        'faces': faces_out,
        'context_disposition': context_disposition,
    }
    mesh_bytes = arena.encode(mesh_record)
    (directory / 'thermal_mesh_record.json').write_bytes(mesh_bytes)

    capture_payload = {
        'input_provenance': input_provenance,
        'input_bindings': input_bindings,
        'schema': D02_CAPTURE_SCHEMA,
        'bindings': {
            'geometry_id': geometry_id,
            'thermal_mesh_record_sha256': hashlib.sha256(mesh_bytes).hexdigest(),
            'legacy_result_id': legacy_result_id,
            'legacy_metadata_sha256': legacy_sha,
            'advance_result_id': advance_ret.result_id,
            'arrays': bound_arrays,
        },
        'compact_mesh_identity': {
            'expected_geometry_id': geometry_id,
            'metadata_digest': metadata_digest,
            'metadata_utf8': metadata_utf8,
            'logical_identity': logical_identity,
            'array_descriptors': compact_array_descriptors,
            'grid_proof_arrays': grid_proof_arrays,
            'tables': compact_tables,
            'grids': compact_grids,
        },
        'provenance': provenance,
        'context_disposition': context_disposition,
        'physical_plan': plan_dict,
        'physical_context': {
            'trajectory_id': trajectory_id,
            'endpoint': endpoint,
            'heat_capacity_j_kg_k': call_snapshot_meta.get('heat_capacity_j_kg_k'),
            'time_s': time_s,
            'duration_s': duration_s,
            'grid_id': grid_id,
            'support_id': support_id,
            'funding_id': funding_id,
            'boundary': boundary,
        },
        'ordered_cell_ids': call_cell_ids,
        'cell_count': cell_count,
        'face_count': face_count,
        'cells': cells_out,
        'faces': faces_out,
    }
    if arena.owner_count != 2 * cell_count + face_count + 1:
        raise ObserverCaptureError('Actual capture owner volume differs')
    capture_bytes = arena.encode(capture_payload)
    (directory / 'd02_correspondence_capture.json').write_bytes(capture_bytes)



def _canon_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _canon_hash(obj):
    return hashlib.sha256(_canon_bytes(obj)).hexdigest()


def predict(arm, history, cli_gib=None):
    """(GiB, basis) of the arm's predicted tree peak, including D02 capture overhead."""
    best = None
    for source, a in history:
        if (a.get('mode'), a.get('layout'), a.get('used'), a.get('input', INPUT)) != (
            arm['mode'],
            arm['layout'],
            [WORKERS, WORKERS],
            INPUT,
        ):
            continue
        if (
            a.get('status') != 'PASS'
            or a.get('exit_code') != 0
            or a.get('stopped')
            or not a.get('tree_peak_mib')
        ):
            continue
        mib = a['tree_peak_mib']
        if a.get('parent_peak_mib') is not None and a.get('worker_peak_mib') is not None:
            mib = max(mib, a['parent_peak_mib'] + WORKERS * a['worker_peak_mib'])
        if best is None or mib > best[0]:
            best = (mib, '%s arm %s' % (source, a['arm']))
    overhead = D02_CAPTURE_OVERHEAD_MIB if arm['mode'] == 'proof' else 0
    if best:
        pred_mib = best[0] + overhead
        return pred_mib / 1024, 'basis: measured base %s (%d MiB) + projected D02 overhead (%.1f MiB)' % (
            best[1],
            best[0],
            overhead,
        )
    for name, value in (
        ('RUNQ_PRED_PEAK_GIB', os.environ.get('RUNQ_PRED_PEAK_GIB')),
        ('--pred-peak-gib', cli_gib),
    ):
        if value is None or value == '':
            continue
        try:
            gib = float(value)
        except ValueError:
            return None, '%s=%r is not a number' % (name, value)
        if not (math.isfinite(gib) and gib > 0):
            return None, '%s=%r is not a positive finite peak' % (name, value)
        pred_gib = gib + (overhead / 1024.0)
        return (
            pred_gib,
            'fallback %s (%.3f GiB + %.1f MiB D02 overhead)' % (name, gib, overhead),
        )
    return None, 'no measured arm of this route, no RUNQ_PRED_PEAK_GIB, no --pred-peak-gib'


def _worker_groups(members, tags):
    for m in members:
        if m.pid not in tags:
            try:
                tags[m.pid] = (WORKER_TAG in ' '.join(m.cmdline()), m.ppid())
            except psutil.Error:
                pass
    groups = {}
    for m in members:
        if m.pid in tags and tags[m.pid][0]:
            pid, steps = m.pid, 0
            while tags.get(tags[pid][1], (False,))[0] and steps < len(tags):
                pid, steps = tags[pid][1], steps + 1
            groups[m.pid] = pid
    return groups






def _child_env(mode):
    removed = sorted(k for k in os.environ if k.upper().startswith('PYTHON'))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    if mode == 'prof':
        env['PYTHONPATH'] = str(HS / 'workerprof')
    return env, removed


def _launch(mode, layout, outdir, k):
    env, removed = _child_env(mode)
    if mode == 'prof':
        env['HS_PROF_DIR'] = str((Path(outdir) / f'arm-{k}').resolve())
    command = [
        sys.executable,
        *CHILD_FLAGS,
        str(Path(__file__).resolve()),
        'child',
        mode,
        str(layout),
        str(Path(outdir).resolve()),
        str(k),
    ]
    return command, env, removed


def _interpreter(mode, PAR, consumer_selection=None):
    f = sys.flags
    if f.hash_randomization or not f.no_user_site or not f.safe_path or f.ignore_environment or f.isolated:
        raise SystemExit(
            'child interpreter: hash_randomization=%d no_user_site=%d safe_path=%r ignore_environment=%d isolated=%d'
            % (f.hash_randomization, f.no_user_site, f.safe_path, f.ignore_environment, f.isolated)
        )
    present = {k.upper(): v for k, v in os.environ.items() if k.upper().startswith('PYTHON')}
    wanted = dict(PYTHONHASHSEED='0')
    if mode == 'prof':
        wanted['PYTHONPATH'] = str(HS / 'workerprof')
    if present != wanted:
        raise SystemExit(
            'child environment: PYTHON* variables %r, expected %r'
            % (sorted(present), sorted(wanted))
        )
    source = Path(PAR.__file__).read_text(encoding='utf8')
    if any(source.count(line) != 1 for line in WORKER_LAUNCH):
        raise SystemExit('functionals_parallel_r1 no longer starts its workers as r8 checks')
    import importlib.util
    if mode == 'proof':
        repair_path = HERE / 'worker-flags-repair' / 'worker_flags_repair.py'
        repair_pin = '14591f6dc606e2e0e954f003018de77f3964ce9f8f50f20da5cf42d0e846687a'
    else:
        if mode not in ('time', 'prof') or consumer_selection is None:
            raise SystemExit('Timing/profiling requires the accepted selected consumer route')
        repair_path = HERE / 'consumer-repair/worker_runtime.py'
        repair_pin = consumer_selection['source_pins'].get(str(repair_path.resolve()))
    if not repair_pin or _file_sha(repair_path) != repair_pin:
        raise SystemExit('Worker isolation repair helper differs from selected bytes')
    repair_spec = importlib.util.spec_from_file_location('plan05_worker_isolation_repair', repair_path)
    repair_module = importlib.util.module_from_spec(repair_spec)
    repair_spec.loader.exec_module(repair_module)
    if mode == 'proof':
        worker_isolation = repair_module.enable_and_probe(PAR, mode=mode)
    else:
        worker_isolation = repair_module.enable_and_probe(
            PAR, mode=mode, source_pins=consumer_selection['source_pins'])
    return dict(
        flags=list(CHILD_FLAGS),
        hash_randomization=f.hash_randomization,
        no_user_site=f.no_user_site,
        safe_path=f.safe_path,
        python_variables=worker_isolation['python_variables_after'],
        worker_probe_hash_randomization=0,
        worker_isolation=worker_isolation,
    )


_SELECTED_ORDER_REPAIR = None


def _install_order_repair(manifest_path, manifest_sha, layout):
    """Select only the frozen additive producer before native issuer import."""
    import importlib.util
    if _file_sha(manifest_path) != manifest_sha:
        raise RuntimeError('Order repair selection changed')
    selection = json.loads(Path(manifest_path).read_text(encoding='utf8'))
    repair = selection['order_repair']
    if repair['schema'] != 'plan05.physical-order-selection.r1' or repair['scope'] != ['lf3', 'lh']:
        raise RuntimeError('Invalid physical-order selection')
    names = ('private_heat_physical_order_r1', 'private_heat_forward_kernel_r13',
             'private_heat_native_issuer_r13')
    if any(name in sys.modules for name in names):
        raise RuntimeError('Order repair must precede native producer/issuer import')
    helper = HERE / 'order-repair/private_heat_physical_order_r1.py'
    forward = HERE / 'order-repair' / layout.name / 'private_heat_forward_kernel_r13.py'
    issuer_path = HERE / 'order-repair' / layout.name / 'private_heat_native_issuer_r13.py'
    for name, path in zip(names, (helper, forward, issuer_path), strict=True):
        expected = repair['source_pins'][str(path.resolve())]
        if selection['source_pins'].get(str(path.resolve())) != expected or _file_sha(path) != expected:
            raise RuntimeError('Unbound or changed order repair source')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    producer = sys.modules[names[1]]
    required = {str(helper.resolve()), str(forward.resolve())}
    if not required <= set(producer._SOURCES):
        raise RuntimeError('Order repair omitted from native producer source closure')
    issuer = sys.modules[names[2]]
    if not {sys.modules[name] for name in names} <= set(issuer._private_modules()):
        raise RuntimeError('Order repair omitted from native loaded-code identity')
    required.add(str(issuer_path.resolve()))
    if not required <= dict(issuer._IMPORTED_SOURCES).keys():
        raise RuntimeError('Order repair omitted from issuer source bindings')
    return dict(schema=repair['schema'], layout=layout.name,
                manifest_path=str(Path(manifest_path).resolve()), manifest_sha256=manifest_sha,
                source_pins={path: repair['source_pins'][path] for path in sorted(required)},
                numerical_tolerances_changed=False, original_metric_mutated=False,
                ordering='authenticated physical cell support; caller row order restored')


def _consumer_selection(path, expected, mode, layout, outdir, index):
    """Validate the frozen proof/authority gate before importing any producer."""
    import importlib.util
    path = Path(path).resolve()
    if _file_sha(path) != expected:
        raise RuntimeError('Consumer selection bytes differ')
    selection = json.loads(path.read_text(encoding='utf8'))
    gate_path = HERE / 'consumer-repair/proof_gate.py'
    pin = selection['source_pins'].get(str(gate_path.resolve()))
    if not pin or _file_sha(gate_path) != pin:
        raise RuntimeError('Consumer gate is outside the selected sources')
    spec = importlib.util.spec_from_file_location('plan05_selected_consumer_gate', gate_path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    selected = gate.validate_child(path, expected, mode, layout, outdir, index)
    claim = gate.read_json(Path(outdir) / 'attempt.json')
    if (claim.get('mode') != 'consumer' or claim.get('manifest_sha256') != expected
            or claim.get('queue_ticket') != 'q22'):
        raise RuntimeError('Consumer child requires the selected owned launch claim')
    launcher_path = HERE / 'launch_plan05_r13.py'
    if selected['source_pins'].get(str(launcher_path.resolve())) != _file_sha(launcher_path):
        raise RuntimeError('Consumer queue boundary is outside the selected sources')
    launcher_spec = importlib.util.spec_from_file_location('plan05_consumer_queue_boundary', launcher_path)
    launcher = importlib.util.module_from_spec(launcher_spec)
    launcher_spec.loader.exec_module(launcher)
    admission = gate.read_json(Path(outdir) / ('arm-' + str(index) + '.admission.json'))
    if (admission.get('manifest_sha256') != expected or admission.get('arm') != index
            or admission.get('mode') != mode or Path(admission['layout']).resolve() != Path(layout).resolve()):
        raise RuntimeError('Consumer child requires its exact per-arm admission')
    launcher.consumer_queue_admission(selected, psutil.virtual_memory().available, os.environ,
                                     admission['prediction'])
    return selected


def child(mode, layout, outdir, k, order_manifest=None, order_manifest_sha=None,
          consumer_manifest=None, consumer_manifest_sha=None):
    global _SELECTED_ORDER_REPAIR
    layout, outdir = Path(layout).resolve(), Path(outdir)
    consumer = None
    if consumer_manifest is not None:
        if mode not in ('time', 'prof') or order_manifest is not None:
            raise RuntimeError('Consumer must select its own timing/profiling producer')
        consumer = _consumer_selection(consumer_manifest, consumer_manifest_sha,
                                       mode, layout, outdir, k)
        if layout.name in ('lf3', 'lh'):
            order_manifest = consumer['order_selection']['path']
            order_manifest_sha = consumer['order_selection']['sha256']
    elif mode != 'proof':
        raise RuntimeError('Accepted consumer selection is required before numerical work')
    control_json_path = layout / 'control.json'
    control_json_bytes = control_json_path.read_bytes()
    control_json_sha = hashlib.sha256(control_json_bytes).hexdigest()
    if layout.name in CONTROL_PINS and control_json_sha != CONTROL_PINS[layout.name]:
        raise SystemExit(
            f'child: layout {layout.name} control.json SHA {control_json_sha} != {CONTROL_PINS[layout.name]}'
        )
    step7_path = C / 'step7_same_call_heat_control.py'
    step7_sha = hashlib.sha256(step7_path.read_bytes()).hexdigest()
    if step7_sha != STEP7_CONTROL_SHA256:
        raise SystemExit(
            f'child: step7 control SHA {step7_sha} != {STEP7_CONTROL_SHA256}'
        )

    info = json.loads(control_json_bytes.decode('utf8'))
    paths = info['paths']
    sys.path[:0] = paths
    import private_heat_functionals_parallel_r1 as PAR

    where = Path(PAR.__file__).resolve()
    if not any(where.parent == Path(p).resolve() for p in paths):
        raise SystemExit('functionals_parallel_r1 did not load from the layout')
    interpreter = _interpreter(mode, PAR, consumer)
    if order_manifest is not None:
        if (mode not in ('proof', 'time', 'prof') or order_manifest_sha is None
                or layout.name not in ('lf3', 'lh')):
            raise RuntimeError('Order repair requires the selected pair producer')
        _SELECTED_ORDER_REPAIR = _install_order_repair(order_manifest, order_manifest_sha, layout)
    runtime = _bind_observer_runtime(layout) if mode == 'proof' else None
    workers = PAR.configure()
    del sys.path[: len(paths)]
    sys.path.append(str(C))
    import step7_same_call_heat_control as CONTROL

    out = outdir / f'arm-{k}.json'
    me = psutil.Process()
    t0, c0 = perf_counter(), process_time()
    arm_dir = outdir / f'arm-{k}'
    stop, disposition = _observer(arm_dir, k, layout, runtime) if mode == 'proof' else (None, None)
    _control_boundary(lambda: CONTROL.child(str(layout), str(out)), stop, disposition, arm_dir)
    if mode == 'proof':
        for req in (
            'arrays.json',
            'legacy_metadata.json',
            'thermal_mesh_record.json',
            'd02_correspondence_capture.json',
            'observer_disposition.json',
        ):
            if not (arm_dir / req).is_file():
                raise SystemExit(f'proof mode capture missing {req} in {arm_dir}')

    wall, cpu = perf_counter() - t0, process_time() - c0
    report = PAR.report()
    allowed = [Path(p).resolve() for p in paths]
    own = {Path(__file__).resolve(), Path(CONTROL.__file__).resolve()}
    if _SELECTED_ORDER_REPAIR is not None:
        own.update(Path(path) for path in _SELECTED_ORDER_REPAIR['source_pins'])
    leaks = sorted(
        {
            str(Path(m.__file__).resolve())
            for m in list(sys.modules.values())
            if getattr(m, '__file__', None)
            and Path(m.__file__).resolve().is_relative_to(WORKSPACE)
            and not Path(m.__file__).resolve().is_relative_to(ENV)
            and not Path(m.__file__).resolve().is_relative_to(HS / 'workerprof')
            and Path(m.__file__).resolve() not in own
            and not any(Path(m.__file__).resolve().is_relative_to(a) for a in allowed)
        }
    )
    result = json.loads(out.read_text(encoding='utf8'))
    calls = [
        dict(
            {
                n: call[n]
                for n in (
                    'faces',
                    'to_reconstruct',
                    'workers',
                    'collected',
                    'in_caller',
                    'fallback',
                    'restarted',
                    'ready_seconds',
                    'seconds',
                    'slowest_face_seconds',
                )
            },
            worker_compute_seconds=round(sum(r['compute_seconds'] for r in call['processes']), 3),
            worker_working_set_peak_max=max(
                (r['working_set_peak_bytes'] for r in call['processes']), default=0
            ),
        )
        for call in report['calls']
    ]
    helpers = Path(paths[1]) if len(paths) > 1 else layout / 'helpers'
    result['ab'] = dict(
        mode=mode,
        layout=str(layout),
        workers_configured=workers,
        calls=calls,
        interpreter=interpreter,
        fallbacks=report['fallbacks'],
        control_wall_seconds=round(wall, 3),
        parent_cpu_seconds=round(cpu, 3),
        leaks=leaks,
        observer_disposition=disposition,
        exact_growth_sha256=hashlib.sha256(
            (helpers / 'private_heat_exact_growth_r1.py').read_bytes()
        ).hexdigest(),
        gmp_resources_sha256=hashlib.sha256(
            (helpers / 'private_heat_gmp_resources_r1.py').read_bytes()
        ).hexdigest(),
        parent_peak_working_set=me.memory_info().peak_wset,
    )
    if consumer is not None:
        result['ab']['consumer_selection'] = dict(
            path=str(Path(consumer_manifest).resolve()), sha256=consumer_manifest_sha,
            order_repair=_SELECTED_ORDER_REPAIR,
            historical_q10='FAIL',
        )
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    calls = report['calls']
    print(
        json.dumps(
            dict(
                arm=k,
                mode=mode,
                status=result['status'],
                leaks=len(leaks),
                recon=[c['seconds'] for c in calls],
                wall=round(wall, 1),
            )
        ),
        flush=True,
    )


def _tree(process):
    try:
        return [process, *process.children(recursive=True)]
    except psutil.Error:
        return [process]


def _check_d02_specs(specs):
    if len(specs) != 2:
        raise SystemExit(
            f'D02 capture scope restricted to exactly 2 arms (got {len(specs)})'
        )
    layouts = []
    for k, spec in enumerate(specs):
        parts = spec.split(':', 2)
        if len(parts) != 3 or parts[0] != 'proof' or not parts[2]:
            raise SystemExit(
                f'arm spec {k} {spec!r}: D02 capture requires proof mode (proof:LABEL:LAYOUT)'
            )
        layout = Path(parts[2]).resolve()
        control_path = layout / 'control.json'
        if not control_path.is_file():
            raise SystemExit(f'arm spec {k} {spec!r}: layout {layout} has no control.json')
        layouts.append(layout.name)
        if layout.name not in CONTROL_PINS:
            raise SystemExit(f'arm spec {k} {spec!r}: layout {layout.name} not in allowed pins')
        sha = hashlib.sha256(control_path.read_bytes()).hexdigest()
        if sha != CONTROL_PINS[layout.name]:
            raise SystemExit(
                f'arm spec {k} {spec!r}: layout {layout.name} control.json SHA {sha} != {CONTROL_PINS[layout.name]}'
            )
    if tuple(layouts) != D02_ALLOWED_LAYOUT_NAMES:
        raise SystemExit(
            f'D02 capture layouts must be exactly {D02_ALLOWED_LAYOUT_NAMES}, got {tuple(layouts)}'
        )
    step7_path = C / 'step7_same_call_heat_control.py'
    if not step7_path.is_file():
        raise SystemExit(f'step7 control file {step7_path} missing')
    step7_sha = hashlib.sha256(step7_path.read_bytes()).hexdigest()
    if step7_sha != STEP7_CONTROL_SHA256:
        raise SystemExit(
            f'step7 control SHA-256 differs ({step7_sha} != {STEP7_CONTROL_SHA256})'
        )


def run(outdir, specs, history_files=(), pred_cli=None):
    _check_d02_specs(specs)
    history = []
    for name in history_files:
        history += [(str(name), a) for a in json.loads(Path(name).read_text(encoding='utf8'))['arms']]
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    arms = []
    for k, spec in enumerate(specs):
        mode, label, layout = spec.split(':', 2)
        arm = dict(arm=k, mode=mode, label=label, layout=str(Path(layout).resolve()))
        arms.append(arm)
        predicted, basis = predict(arm, history + [('this run', a) for a in arms[:-1]], pred_cli)
        arm.update(
            input=INPUT,
            predicted_peak_gib=None if predicted is None else round(predicted, 3),
            prediction_basis=basis,
        )
        if predicted is None:
            arm['stopped'] = 'start gate: no peak prediction'
            break
        gate = int((predicted * 1.2 + 2) * GIB)
        waited = 0
        free = psutil.virtual_memory().available
        while free < gate and waited < 600:
            sleep(15)
            waited += 15
            free = psutil.virtual_memory().available
        arm.update(
            start_gate_gib=round(gate / GIB, 2),
            free_gib_at_start=round(free / GIB, 2),
            gate_waited_s=waited,
        )
        if free < gate:
            arm['stopped'] = 'start gate'
            break
        command, env, removed = _launch(mode, arm['layout'], outdir, k)
        arm.update(child_flags=list(CHILD_FLAGS), removed_python_variables=removed)
        began = perf_counter()
        cpu0 = psutil.cpu_times()
        with open(outdir / f'arm-{k}.log', 'wb') as handle:
            process = subprocess.Popen(
                command, cwd=C, env=env, stdout=handle, stderr=subprocess.STDOUT
            )
            watched = psutil.Process(process.pid)
            peak_ws, low = 0, psutil.virtual_memory().available
            parent_peak, worker_peak, worker_pids, tags = 0, 0, set(), {}
            while process.poll() is None:
                members = _tree(watched)
                groups = _worker_groups(members, tags)
                ws, own, per_worker = 0, 0, {}
                for m in members:
                    try:
                        rss = m.memory_info().rss
                    except psutil.Error:
                        continue
                    ws += rss
                    if m.pid in groups:
                        per_worker[groups[m.pid]] = per_worker.get(groups[m.pid], 0) + rss
                    else:
                        own += rss
                available = psutil.virtual_memory().available
                peak_ws, low = max(peak_ws, ws), min(low, available)
                parent_peak, worker_peak = max(parent_peak, own), max([worker_peak, *per_worker.values()])
                worker_pids.update(per_worker)
                if ws > RSS_GUARD or available < FREE_FLOOR:
                    arm['stopped'] = f'guard: tree {ws} B, available {available} B'
                    for m in reversed(members):
                        try:
                            m.kill()
                        except psutil.Error:
                            pass
                    break
                sleep(0.5)
            process.wait()
        cpu1 = psutil.cpu_times()
        busy = (sum(cpu1._asdict().values()) - cpu1.idle) - (sum(cpu0._asdict().values()) - cpu0.idle)
        arm.update(
            exit_code=process.returncode,
            arm_wall_seconds=round(perf_counter() - began, 2),
            tree_peak_mib=peak_ws >> 20,
            available_low_mib=low >> 20,
            machine_busy_cpu_seconds=round(busy, 1),
            parent_peak_mib=parent_peak >> 20,
            worker_peak_mib=worker_peak >> 20,
            worker_processes=len(worker_pids),
        )
        out = outdir / f'arm-{k}.json'
        if process.returncode == 0 and out.is_file():
            res = json.loads(out.read_text(encoding='utf8'))
            ab = res['ab']
            own = ab['parent_cpu_seconds'] + sum(c['worker_compute_seconds'] for c in ab['calls'])
            arm.update(
                status=res['status'],
                leaks=len(ab['leaks']),
                legacy_s=round(res['legacy']['seconds'], 2),
                compact_s=round(res['compact']['seconds'], 2),
                recon_s=[c['seconds'] for c in ab['calls']],
                worker_cpu_s=[c['worker_compute_seconds'] for c in ab['calls']],
                fallback=[c['fallback'] for c in ab['calls']],
                used=[c['workers'] for c in ab['calls']],
                other_load_cpus=round((busy - own) / max(arm['arm_wall_seconds'], 1e-9), 2),
                arrays=res['arrays'],
                result_id=res['compact']['result_id'],
                exact_growth=ab['exact_growth_sha256'][:12],
                gmp_resources=ab['gmp_resources_sha256'][:12],
            )
        else:
            arm.setdefault('stopped', 'arm did not complete; see its log')
            break
    (outdir / 'summary.json').write_text(json.dumps(dict(arms=arms), indent=1), encoding='utf8')
    print('arm mode label status leaks legacy_s compact_s recon_s worker_cpu_s other_cpus tree_MiB exact_growth')
    for a in arms:
        if 'status' not in a:
            print(a['arm'], a['mode'], a['label'], 'STOPPED', a.get('stopped'))
            continue
        print(
            a['arm'],
            a['mode'],
            a['label'],
            a['status'],
            a['leaks'],
            a['legacy_s'],
            a['compact_s'],
            a['recon_s'],
            a['worker_cpu_s'],
            a['other_load_cpus'],
            a['tree_peak_mib'],
            a['exact_growth'],
        )


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    if len(sys.argv) < 2:
        raise SystemExit('usage: run, child, or flags')
    if sys.argv[1] == 'child':
        if len(sys.argv) == 9 and sys.argv[6] == '--consumer-selection':
            child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]),
                  consumer_manifest=sys.argv[7], consumer_manifest_sha=sys.argv[8])
        elif len(sys.argv) == 9 and sys.argv[6] == '--order-repair-selection':
            child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[7], sys.argv[8])
        elif len(sys.argv) == 6:
            child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
        else:
            raise SystemExit('child arguments differ from the selected route')
    elif sys.argv[1] == 'flags':
        sys.path[:0] = json.loads((Path(sys.argv[3]).resolve() / 'control.json').read_text(encoding='utf8'))['paths']
        import private_heat_functionals_parallel_r1 as PAR

        print(json.dumps(_interpreter(sys.argv[2], PAR)), flush=True)
    elif sys.argv[1] == 'run':
        raise SystemExit('Standalone run is disabled; use launch_plan05_r13.py')
    else:
        raise SystemExit('child or flags; launch pairs with launch_plan05_r13.py')


if __name__ == '__main__':
    main()
