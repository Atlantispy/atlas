"""Completed-query restart for a live context with declared build provenance.

An OS lock serialises durable writers. A context with no declared build
computes normally without opening, reading or publishing a durable query cache.
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

from atlas_shared.errors import AtlasError
from atlas_tectonics.integration.geometry import differential_geometry as G
from atlas_tectonics.integration.parallel.binding import capture_runtime, canonical, request_fields
from atlas_tectonics.integration.parallel.results import (
    _validated_volume, raw_capacity, validation_capacity,
)
from atlas_tectonics.integration.geometry.component_volume_batch import _QueryArena, _QueryFailureOwner
from atlas_tectonics.integration.resources import WorkBudget


HEADER = struct.Struct('<8sII32s32s')
MAGIC = b'ATECP01\n'
MAX_BINDING = 32768
MAX_PAYLOAD = 1 << 20
OWNER_BYTES = 262144
SCHEMA = 'private.completed-endpoint-query.v1'
# Publish completed misses in bounded groups.
HOLD_ENTRIES = 64
# 64 x 22,096, the median work_units of the b0 interval's 7,181 completed
# records: a costly record publishes at once, alone if need be. No clock.
HOLD_WORK = 64*22096


class CheckpointRefused(ValueError, AtlasError):
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
    full_checks/cached_checks count completed strict checks by route; they are
    observations only and never enter a key, binding or result.
    hits_restart/hits_after_write/hits_warm split ``hits`` by the key's history
    in this open (WP17 Tier 1; observations only, likewise): the first hit on
    a key written in this open is after-write, held or committed; a later hit
    on an already hit key is warm; any other first hit is restart. Keys are
    kept as 64-bit prefixes, at most min(max_entries, SPLIT_MAX_KEYS) of them
    (the keys one open can touch, E + w, never exceed the quota; 2**18 keys
    measured about 20 MiB); past that bound split_status is TRUNCATED and the
    split stops, hits does not. entries_at_open is the committed *.query count
    of the open's scan (None for columnar: its rows are counted by its backend).
    """
    SPLIT_MAX_KEYS = 1 << 18  # the Tier 1 map bound, with max_entries (about 80 B per key, measured)
    def __init__(self, directory, *, context, budget, cancel=None,
                 max_store_bytes=1 << 30, max_entries=100000, storage='files'):
        if (type(max_store_bytes) is not int or max_store_bytes < HEADER.size
                or type(max_entries) is not int or max_entries < 1):
            raise ValueError('explicit positive checkpoint disk limits required')
        if cancel is not None and not callable(cancel):
            raise TypeError('cancel must be a callable or None')
        if storage not in ('files', 'columnar'):
            raise ValueError('checkpoint storage must be files or columnar')
        self.storage, self._compact = storage, None
        self.directory = _absolute_path(directory)
        self.context, self.budget, self.cancel = context, budget, cancel
        self.max_store_bytes, self.max_entries = max_store_bytes, max_entries
        self._stack, self._lock = ExitStack(), None
        self._memory = ExitStack()
        self._owner = _QueryFailureOwner(self._memory)
        self._active = self._closed = False
        self._pending = self._runtime = None
        self._runtime_digest = None
        self._last_completed = None
        self._used = self._entries = 0
        self.hits = self.misses = self.written = self.incomplete = 0
        self.full_checks = self.cached_checks = 0
        self.hits_restart = self.hits_after_write = self.hits_warm = 0
        # Key prefix -> False (written in this open, not hit yet) or True (hit in this open).
        self.split_status, self.entries_at_open, self._seen = 'COMPLETE', None, {}
        # key -> (partial path, final path): written and synced, not yet visible.
        self._held, self._held_work = {}, 0

    def _live(self):
        if not self._active:
            raise RuntimeError('checkpoint store requires its active owner')
        if self.cancel is not None and self.cancel():
            raise CancelledError('endpoint checkpoint operation cancelled')

    def _check(self):
        self._live()
        self.context.verify()
        self.cached_checks += 1

    def __enter__(self):
        if self._active or self._closed:
            raise RuntimeError('checkpoint store cannot be re-entered')
        try:
            _ledger_limits(self.budget)
            self._memory.enter_context(self.budget.reserve(
                OWNER_BYTES, category='endpoint-checkpoint-owner'))
            self._runtime = canonical(capture_runtime(self.context))
            self.full_checks = 1
            if len(self._runtime) > MAX_BINDING//2:
                raise CheckpointRefused('execution identity metadata exceeds bounded owner')
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
            committed = 0
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if entry.name == 'owner.lock':
                        continue
                    info = _plain_path(entry.path).stat()
                    self._used += info.st_size
                    # Column-store rows (and its recovery journal) are counted
                    # by that backend; a hot journal is not an extra query.
                    if not (self.storage == 'columnar' and entry.name in
                            ('completed.sqlite', 'completed.sqlite-journal')):
                        self._entries += 1
                        if entry.name.endswith('.query'):
                            committed += 1
                    if self._used > self.max_store_bytes or self._entries > self.max_entries:
                        raise CheckpointRefused('checkpoint store exceeds configured disk bounds')
            self.entries_at_open = None if self.storage == 'columnar' else committed
            # This selected generation supports files only. Preserve the
            # missing-companion refusal before activation or any query,
            # including when an optional companion is later present.
            if self.storage == 'columnar':
                raise ModuleNotFoundError(
                    "No module named 'atlas_tectonics.compact_query_store'",
                    name='atlas_tectonics.compact_query_store')
            self._active = True
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        self._active, self._closed = False, True
        compact, self._compact = self._compact, None
        if compact is not None:
            compact.close()
        self._pending = self._runtime = None
        self._seen = {}
        self.context = self.budget = self.cancel = None
        self._stack.close()
        self._lock = None
        # A failed before/after frame can still retain binding metadata. Its
        # local owner keeps the reservation until that frame dies, independently
        # of the OS lock, which must close immediately for an explicit reopen.
        self._owner = None

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self.flush()
        finally:
            self.close()
        return False

    @property
    def unflushed(self):
        return len(self._held)

    def flush(self):
        """Publish every held completed miss after ONE fresh strict check."""
        if self._owner is None:
            raise RuntimeError('checkpoint store is closed')
        if not self._held:
            return
        try:
            self._check()
        except BaseException:
            # A refused check drops its group, never retried: base never publishes a refused record.
            # The partial files stay, already counted, as after a stopped process.
            self._held, self._held_work = {}, 0
            raise
        while self._held:
            key, (partial, path) = next(iter(self._held.items()))
            if path.exists():
                raise CheckpointRefused('checkpoint appeared outside the single writer')
            os.replace(partial, path)
            del self._held[key]
            self.written += 1
        self._held_work = 0

    @property
    def last_completed(self):
        """(full binding key, from_checkpoint) for the last completed call.

        This out-of-band immutable tuple never changes measure bytes. A caller
        with speculative scheduling MUST consume a hit in serial request order
        without treating disk-read time as numerical learning. No scheduler
        advancement or speculative-job exclusion is implemented in this module.
        """
        return self._last_completed

    def _split_full(self):
        # The Tier 1 memory bound (class docstring): past it the split stops.
        if len(self._seen) < min(self.max_entries, self.SPLIT_MAX_KEYS):
            return False
        self.split_status, self._seen = 'TRUNCATED', {}
        return True

    def _split_hit(self, key):
        """Observation only: classify one counted hit by its key's history in this open."""
        if self.split_status == 'COMPLETE':
            prefix = int(key[:16], 16)
            state = self._seen.get(prefix)
            if state is None and self._split_full():
                return
            if state is None:
                self.hits_restart += 1
            elif state:
                self.hits_warm += 1
            else:
                self.hits_after_write += 1
            self._seen[prefix] = True

    def _split_written(self, key):
        """Observation only: a key written in this open, held or committed."""
        if self.split_status == 'COMPLETE':
            prefix = int(key[:16], 16)
            if prefix not in self._seen and not self._split_full():
                self._seen[prefix] = False

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
        actual_input = support.support_id
        if request['support_id'] != actual_input:
            raise CheckpointRefused('request does not bind actual issued support bytes')
        limits = _ledger_limits(budget)
        if self._runtime_digest is None:
            self._runtime_digest = hashlib.sha256(self._runtime).hexdigest()
        binding = canonical(dict(schema=SCHEMA, request=request,
            input_sha256=actual_input, runtime_sha256=self._runtime_digest,
            positive_witness=True, relative_error=None, ledger_ancestry=limits))
        if len(binding) > MAX_BINDING:
            raise CheckpointRefused('endpoint request exceeds checkpoint binding bound')
        key = hashlib.sha256(binding).hexdigest()
        if key in self._held:
            self.flush()
        self._pending = (binding, key, False)
        with _QueryArena(budget) as arena:
            payload = (None if self._compact is None else
                       self._compact.read(binding, key, arena))
            if payload is None:
                payload = self._read_file(binding, key, arena)
            if payload is None:
                self.misses += 1
                return None
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
        self._split_hit(key)
        return result

    def _read_file(self, binding, key, arena):
        # Legacy entries remain readable, even when the successor writes columns.
        path = self.directory / (key+'.query')
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        _plain_path(path)
        if not HEADER.size < info.st_size <= HEADER.size+MAX_BINDING+MAX_PAYLOAD:
            raise CheckpointRefused('checkpoint file size is outside bounds')
        arena.stack.enter_context(self.budget.reserve(
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
                    or bytes.fromhex(key) != bound_hash
                    or hashlib.sha256(payload).digest() != result_hash or bound != binding):
                raise CheckpointRefused('checkpoint content/binding differs')
        return payload

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
            if self._compact is not None:
                self._compact.write(binding, key, payload, arena, self._check)
                self.written += 1
                self._split_written(key)
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
            # Held, not visible: flush() checks once, then publishes the group.
            self._held[key] = (partial, path)
            self._held_work += record['work_units']
            # File fsync + same-directory atomic replace guarantee no accepted
            # half-entry. Power loss may lose a completed entry; that is a miss,
            # never proof of whole-filesystem durability.
            self._entries += 1
            self._used += size
            self._split_written(key)
            self._last_completed = (key, False)
            self._pending = None
            if len(self._held) >= HOLD_ENTRIES or self._held_work >= HOLD_WORK:
                self.flush()


# Files-only selected generation: no static or dynamic import of the
# unselected columnar companion. Enabling another backend requires a
# separately supported source selection; __enter__ preserves refusal.
