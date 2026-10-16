"""Private completed-query restart, never adaptive-frontier or checkpoint migration.

Only the native ComponentVolumeQueries seam calls before/after. Entries are
trusted local execution artifacts, not a public arbitrary-JSON proof API. File
digests detect corruption; they do not authenticate a hostile writer. A native
strict ExecutionContext verifies actual source, loaded code and runtime at both
reuse/publication boundaries. An OS lock serialises writers and dies on crash.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
from concurrent.futures import CancelledError
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import uuid

from . import integration_differential_geometry as G
from .integration_parallel_binding import capture_runtime, canonical, request_fields
from .integration_parallel_results import (
    _validated_volume, raw_capacity, validation_capacity,
)
from .integration_component_volume_batch import _QueryArena, _QueryFailureOwner
from .resources import WorkBudget


HEADER = struct.Struct('<8sII32s32s')
MAGIC = b'ATECP01\n'
MAX_BINDING = 32768
MAX_PAYLOAD = 1 << 20
OWNER_BYTES = 262144
SCHEMA = 'private.completed-endpoint-query.v1'


class CheckpointRefused(ValueError):
    """An existing entry cannot establish safe completed-query reuse."""


def _plain_path(path, *, directory=False):
    path = _absolute_path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CheckpointRefused('linked checkpoint path refused')
    if not (path.is_dir() if directory else path.is_file()):
        raise CheckpointRefused('ordinary checkpoint directory/file required')
    return path


def _absolute_path(path):
    value = os.path.abspath(os.fspath(path))
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
    return Path(value)


def _ledger_limits(budget):
    result = []
    while budget is not None:
        if (type(budget) is not WorkBudget or any(name in vars(budget) for name in
                ('reserve', 'reserve_predicate_work', 'try_reserve', '_settle'))):
            raise TypeError('unchanged plain WorkBudget ancestry required')
        result.append([budget.max_bytes, budget.max_predicate_work_units])
        if len(result) > 8:
            raise CheckpointRefused('checkpoint ledger ancestry exceeds eight')
        budget = budget._parent
    return result


class _CompletedAllowance:
    """Recorded plain-ledger ceilings, NOT a fabricated live-worker FitWitness."""
    def __init__(self, limits):
        self.limits = limits

    def admits_work(self, units):
        return all(units <= work if work is not None else 32*units <= size
                   for size, work in self.limits)


def _validate(payload, request, limits, arena, *, require_complete=True):
    # Scan and reserve before json.loads; preserve all diagnostic frames through
    # query arena's existing failure ownership. No decoded graph is retained.
    arena.stack.enter_context(arena.resource.reserve(
        validation_capacity(payload), category='endpoint-checkpoint-validation'))
    record = json.loads(payload)
    if (type(record) is not dict or canonical(record) != payload
            or not _validated_volume(record, canonical(request), _CompletedAllowance(limits))):
        raise CheckpointRefused('checkpoint result shape/request/work differs')
    scalars = [record[key] for key in
               ('lower_m3', 'upper_m3', 'positive_witness_m3', 'max_width_m3')]
    # Bound rational conversion/comparison before constructing any large ints.
    # Four bits per hex character is an upper bound. The existing exact-work
    # coefficient is preserved; result JSON is already included above.
    bits = 4*sum(len(text) for pair in scalars for text in pair)
    arena.stack.enter_context(arena.resource.reserve(
        65536+128*bits+256*len(scalars), category='endpoint-checkpoint-exact-validation'))
    low, high, witness, width = (G.W._decode(pair) for pair in scalars)
    complete = high-low <= width and (high == 0 or witness > 0)
    if (not 0 <= witness <= low <= high or record['met'] is not complete
            or require_complete and not complete):
        raise CheckpointRefused('checkpoint fails original width/positivity constraints')
    return record


class EndpointCheckpoints:
    """Context-bound single writer; stores ONE completed result per exact key.

    The dedicated directory must already exist. No graph, partition or decoded
    support survives a call. A single pending binding is bounded by MAX_BINDING.
    Unknown/partial files consume the quota but are never queried as results.
    Corrupt committed entries refuse explicitly. Stale identities are misses.
    Closing never deletes entries, including crash-left partials. The OS lock
    is released even on process death; there is no stale-lock guessing.
    """
    def __init__(self, directory, *, context, budget, cancel=None,
                 max_store_bytes=1 << 30, max_entries=100000):
        if (type(max_store_bytes) is not int or max_store_bytes < HEADER.size
                or type(max_entries) is not int or max_entries < 1):
            raise ValueError('explicit positive checkpoint disk limits required')
        if cancel is not None and not callable(cancel):
            raise TypeError('cancel must be a callable or None')
        self.directory = _absolute_path(directory)
        self.context, self.budget, self.cancel = context, budget, cancel
        self.max_store_bytes, self.max_entries = max_store_bytes, max_entries
        self._stack, self._lock = ExitStack(), None
        self._memory = ExitStack()
        self._owner = _QueryFailureOwner(self._memory)
        self._active = self._closed = False
        self._pending = self._runtime = None
        self._last_completed = None
        self._used = self._entries = 0
        self.hits = self.misses = self.written = self.incomplete = 0

    def _live(self):
        if not self._active:
            raise RuntimeError('checkpoint store requires its active owner')
        if self.cancel is not None and self.cancel():
            raise CancelledError('endpoint checkpoint operation cancelled')

    def _check(self):
        # Fresh strict identity: re-reads every source and walks the loaded
        # inventory. After entry it runs exactly at the two boundaries that can
        # expose disk state: before a hit is issued, before a miss is published.
        self._live()
        # No caller-supplied source hash or source-identity override is accepted.
        runtime = canonical(capture_runtime(self.context))
        if self._runtime is not None and runtime != self._runtime:
            raise CheckpointRefused('checkpoint execution/runtime changed')
        return runtime

    def __enter__(self):
        if self._active or self._closed:
            raise RuntimeError('checkpoint store cannot be re-entered')
        try:
            _ledger_limits(self.budget)
            self._memory.enter_context(self.budget.reserve(
                OWNER_BYTES, category='endpoint-checkpoint-owner'))
            self.directory = _plain_path(self.directory, directory=True)
            lock = self.directory / 'owner.lock'
            if lock.exists():
                _plain_path(lock)
            self._lock = open(lock, 'a+b', buffering=0)
            self._stack.callback(self._lock.close)
            if os.name == 'nt':
                import msvcrt
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if entry.name == 'owner.lock':
                        continue
                    info = _plain_path(entry.path).stat()
                    self._used += info.st_size
                    self._entries += 1
                    if self._used > self.max_store_bytes or self._entries > self.max_entries:
                        raise CheckpointRefused('checkpoint store exceeds configured disk bounds')
            self._active = True
            self._runtime = self._check()
            if len(self._runtime) > MAX_BINDING//2:
                raise CheckpointRefused('execution identity metadata exceeds bounded owner')
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        self._active, self._closed = False, True
        self._pending = self._runtime = None
        self.context = self.budget = self.cancel = None
        self._stack.close()
        self._lock = None
        # A failed before/after frame can still retain binding metadata. Its
        # local owner keeps the reservation until that frame dies, independently
        # of the OS lock, which must close immediately for an explicit reopen.
        self._owner = None

    def __exit__(self, *_):
        self.close()
        return False

    @property
    def last_completed(self):
        """(full binding key, from_checkpoint) for the last completed call.

        This out-of-band immutable tuple never changes measure bytes. A caller
        with speculative scheduling MUST consume a hit in serial request order
        without treating disk-read time as numerical learning. No scheduler
        advancement or speculative-job exclusion is implemented in this module.
        """
        return self._last_completed

    def before(self, support, request, budget):
        """Native seam only, AFTER original component/layer/cell/query checks."""
        owner = self._owner
        if owner is None:
            raise RuntimeError('checkpoint store is closed')
        if self._pending is not None:
            raise RuntimeError('previous checkpoint query did not complete')
        self._last_completed = None
        # Liveness/cancel only. The binding uses the runtime fixed at entry; a
        # hit is verified once before issue below, a miss once before publish.
        self._live()
        if (budget is not self.budget or type(support) is not G.DifferentialSupport
                or support._resource is not budget):
            raise TypeError('same native support and checkpoint budget required')
        request_fields(request)
        actual_input = hashlib.sha256(support._json).hexdigest()
        if request['support_id'] != actual_input:
            raise CheckpointRefused('request does not bind actual issued support bytes')
        limits = _ledger_limits(budget)
        binding = canonical(dict(schema=SCHEMA, request=request,
            input_sha256=actual_input, runtime_sha256=hashlib.sha256(self._runtime).hexdigest(),
            positive_witness=True, relative_error=None, ledger_ancestry=limits))
        if len(binding) > MAX_BINDING:
            raise CheckpointRefused('endpoint request exceeds checkpoint binding bound')
        key = hashlib.sha256(binding).hexdigest()
        self._pending = (binding, key, False)
        path = self.directory / (key+'.query')
        try:
            info = path.lstat()
        except FileNotFoundError:
            self.misses += 1
            return None
        _plain_path(path)
        if not HEADER.size < info.st_size <= HEADER.size+MAX_BINDING+MAX_PAYLOAD:
            raise CheckpointRefused('checkpoint file size is outside bounds')
        with _QueryArena(budget) as arena:
            arena.stack.enter_context(budget.reserve(
                raw_capacity(info.st_size), category='endpoint-checkpoint-read'))
            with open(path, 'rb') as source:
                opened = os.fstat(source.fileno())
                if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
                    raise CheckpointRefused('checkpoint changed before bounded read')
                header = source.read(HEADER.size)
                magic, bound_size, size, bound_hash, result_hash = HEADER.unpack(header)
                if (magic != MAGIC or not 0 < bound_size <= MAX_BINDING
                        or not 0 < size <= MAX_PAYLOAD
                        or HEADER.size+bound_size+size != info.st_size):
                    raise CheckpointRefused('checkpoint header/length differs')
                bound = source.read(bound_size)
                payload = source.read(size)
                after = os.fstat(source.fileno())
                if (len(bound) != bound_size or len(payload) != size or source.read(1)
                        or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns)
                        or hashlib.sha256(bound).digest() != bound_hash
                        or hashlib.sha256(payload).digest() != result_hash or bound != binding):
                    raise CheckpointRefused('checkpoint content/binding differs')
            record = _validate(payload, request, limits, arena)
            # Reserve the original reported work envelope during adoption, as
            # well as current validation scratch. This is reuse admission, not
            # an assertion that historical predicate work executed again.
            work = record['work_units']
            if budget.max_predicate_work_units is None:
                arena.stack.enter_context(budget.reserve(32*work, category='endpoint-checkpoint-work-envelope'))
            else:
                arena.stack.enter_context(budget.reserve_predicate_work(
                    work, category='endpoint-checkpoint-work-envelope'))
            self._check()
            result = G._issue(G.DifferentialMeasure, record, budget)
            if result._json != payload:
                raise CheckpointRefused('native issued checkpoint bytes differ')
        self._pending = (binding, key, True)
        self.hits += 1
        return result

    def after(self, result, budget):
        """Called only on the exact result returned by the native query body."""
        owner = self._owner
        if owner is None:
            raise RuntimeError('checkpoint store is closed')
        # A hit was verified before issue; a completed miss is verified at the
        # publication boundary below; an unmet result is never stored.
        self._live()
        if self._pending is None:
            raise RuntimeError('checkpoint result has no native validated query')
        if (type(result) is not G.DifferentialMeasure or result._resource is not budget
                or budget is not self.budget):
            raise TypeError('native issued result on the same budget required')
        binding, key, hit = self._pending
        if hit:
            self._last_completed = (key, True)
            self._pending = None
            return
        payload = result._json
        if not 0 < len(payload) <= MAX_PAYLOAD:
            raise CheckpointRefused('completed result exceeds checkpoint payload bound')
        with _QueryArena(budget) as arena:
            arena.stack.enter_context(budget.reserve(
                raw_capacity(len(payload))+8*len(binding), category='endpoint-checkpoint-write'))
            query = json.loads(binding)
            record = _validate(payload, query['request'], query['ledger_ancestry'], arena,
                               require_complete=False)
            if record.get('met') is not True:
                self.incomplete += 1
                self._last_completed = (key, False)
                self._pending = None
                return
            size = HEADER.size+len(binding)+len(payload)
            if self._entries+1 > self.max_entries or self._used+size > self.max_store_bytes:
                raise CheckpointRefused('checkpoint disk quota exhausted')
            header = HEADER.pack(MAGIC, len(binding), len(payload),
                hashlib.sha256(binding).digest(), hashlib.sha256(payload).digest())
            path = self.directory / (key+'.query')
            if path.exists():
                raise CheckpointRefused('checkpoint appeared outside the single writer')
            partial = self.directory / (key+'.partial-'+uuid.uuid4().hex)
            # A stopped process can leave this incomplete file, but the read
            # path considers only .query. No committed filename appears early.
            with open(partial, 'xb', buffering=0) as target:
                for data in (header, binding, payload):
                    offset = 0
                    while offset < len(data):
                        count = target.write(memoryview(data)[offset:])
                        if not count:
                            raise OSError('short checkpoint write')
                        offset += count
                os.fsync(target.fileno())
            self._check()
            os.replace(partial, path)
            # File fsync + same-directory atomic replace guarantee no accepted
            # half-entry. Power loss may lose a completed entry; that is a miss,
            # never proof of whole-filesystem durability.
            self._entries += 1
            self._used += size
            self.written += 1
            self._last_completed = (key, False)
            self._pending = None
