"""Private completed-query restart, never adaptive-frontier or checkpoint migration.

Only the native ComponentVolumeQueries seam calls before/after. Entries are
trusted local execution artifacts, not a public arbitrary-JSON proof API. File
digests detect corruption; they do not authenticate a hostile writer. A native
strict ExecutionContext verifies actual source, loaded code and runtime at both
reuse/publication boundaries. An OS lock serialises writers and dies on crash.

Cached source re-hash (W5-A, owner decision of 14 October 2026). The strict
check before a hit is issued and before a miss is published used to re-read and
hash all package sources on every query (about 30 ms of a 41-70 ms check). The
entry check and the first reuse/publication check of every store remain the
unchanged native full check (capture_runtime: every package source re-read and
hashed, then the loaded-inventory walk), so the first check in a process is
always full. A full boundary check also records, for every package *.py file
(reuse._source_bytes' own rglob membership and file bound), its non-following
stat identity (st_mode, st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns),
taken immediately before AND after the full re-read; the record is kept only
when both agree. Each later boundary check stats every source again and
compares membership (an added or removed package file) and every identity. Only
when all are unchanged and the last full re-hash began less than
MAX_CACHED_SOURCE_AGE_S ago is the re-read skipped, reusing that re-hash's
verified digest; otherwise the full check runs and renews the record.
Everything else is verified on every check exactly as before: the interpreter
seed, the exact strict ExecutionContext, a closed context, the whole loaded
callable/default/constant inventory, the identity/runtime shape and equality
with the runtime fixed at entry. Any refusal discards the record and refuses as
before; nothing is issued or published.

The bounded relaxation, precisely: a change to a package source made after the
last full re-hash that keeps its size, mtime, ctime (creation time on Windows),
inode, device and mode, and adds or removes no package file, is not seen by
THIS check for up to MAX_CACHED_SOURCE_AGE_S. The periodic full re-read exists
because this store is durable and reusable: it outlives the run and survives
interruptions, so a result computed by silently changed code and published here
would be reused by later runs. The age bound caps the window in which that can
happen. The run itself still sees any change: the runner's mandatory full
RestartSources.verify() at start and end re-hashes every source before any PASS.
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
from time import monotonic
import uuid

from . import integration_differential_geometry as G
from . import integration_parallel_binding as _binding
from . import reuse as _reuse
from ._validation import TectonicsError
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
# Maximum age (monotonic seconds) of the last full source re-hash that a
# boundary check may reuse; older, the check re-reads and re-hashes everything.
MAX_CACHED_SOURCE_AGE_S = 300


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


def _source_identities(root, limit):
    """Every package source's non-following stat identity, or None. Reads nothing.

    Membership is reuse._source_bytes' own rule: root.rglob('*.py'), at most
    ``limit`` files. None (a stat failure, a non-regular member, a membership
    past the bound) always sends the caller to the full native check, which
    then accepts or refuses exactly as before.
    """
    try:
        names = []
        for path in root.rglob('*.py'):
            if len(names) >= limit:
                return None
            names.append(str(path))
        out = []
        for name in sorted(names):
            info = os.lstat(name)
            if not stat.S_ISREG(info.st_mode):
                return None
            out.append((name, info.st_mode, info.st_dev, info.st_ino, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns))
        return tuple(out)
    except OSError:
        return None


def _verified_runtime(context):
    """capture_runtime(context) with only its source re-read answered by the record.

    Statement for statement integration_parallel_binding.capture_runtime and
    reuse.ExecutionContext.identity -> verify() -> verify_boundary(), except
    verify_boundary's first comparison (every source re-read against the
    captured digests), which the caller's unchanged stat identities answer.
    The loaded inventory is walked in full, with the same refusal texts. Used
    only for a record hit; the tests pin the mirrored native function bodies.
    """
    seed = _binding.interpreter_seed()
    if type(context) is not _reuse.ExecutionContext or context._mode != 'strict':
        raise TypeError('the actual strict scientific ExecutionContext is required')
    if context._closed:
        raise TectonicsError("execution context is closed")
    if context._expected is not None:
        helper = context._comparison_token
        if (_reuse._verify_callable_inventory is not helper[1]
                or _reuse._verify_callable_inventory.__code__ is not helper[2]):
            raise TectonicsError("loaded implementation changed")
        _reuse._verify_callable_inventory(context.backend, context._expected, context._constants,
                                          context._modules, context._immutable)
    else:
        _, tokens, constants = _reuse._callable_inventory(context.backend, context._modules)
        if constants != context._constants or len(tokens) != len(context._tokens):
            raise TectonicsError("loaded implementation changed")
        for now, old in zip(tokens, context._tokens, strict=True):
            if now[0] != old[0] or now[1] is not old[1] or now[2] is not old[2] or now[3] != old[3]:
                raise TectonicsError("loaded implementation changed")
    identity = context._identity
    runtime = context._runtime
    if not _binding._digest(identity) or type(runtime) is not dict or runtime.keys() != {'versions', 'binaries'}:
        raise ValueError('complete scientific execution identity/runtime required')
    return {'execution_identity': identity, 'execution_runtime': runtime, 'interpreter_seed': seed}


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
    """
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
        self._last_completed = None
        self._used = self._entries = 0
        self.hits = self.misses = self.written = self.incomplete = 0
        # (stat identities, monotonic start of their passing full re-hash) or None.
        self._sources_seen = None
        self.full_checks = self.cached_checks = 0

    def _live(self):
        if not self._active:
            raise RuntimeError('checkpoint store requires its active owner')
        if self.cancel is not None and self.cancel():
            raise CancelledError('endpoint checkpoint operation cancelled')

    def _check(self, *, boundary=True):
        # Fresh strict identity. After entry it runs exactly at the two
        # boundaries that can expose disk state: before a hit is issued, before
        # a miss is published. Entry (boundary=False) is always the full native
        # check; a boundary check skips only the source re-read, and only when
        # the source-identity record allows it (module docstring).
        self._live()
        try:
            # No caller-supplied source hash or source-identity override is accepted.
            runtime, route = self._strict_runtime(boundary)
            if self._runtime is not None and runtime != self._runtime:
                raise CheckpointRefused('checkpoint execution/runtime changed')
        except BaseException:
            self._sources_seen = None
            raise
        if route == 'cached':
            self.cached_checks += 1
        else:
            self.full_checks += 1
        return runtime

    def _strict_runtime(self, boundary):
        started = monotonic()
        root, limit = Path(_reuse.__file__).parent, _reuse._SOURCE_FILES
        identities = _source_identities(root, limit) if boundary else None
        seen = self._sources_seen
        if (identities is not None and seen is not None and identities == seen[0]
                and started-seen[1] < MAX_CACHED_SOURCE_AGE_S):
            return canonical(_verified_runtime(self.context)), 'cached'
        self._sources_seen = None
        runtime = canonical(capture_runtime(self.context))
        # Recorded only when no identity moved while every byte was re-read.
        if identities is not None and _source_identities(root, limit) == identities:
            self._sources_seen = (identities, started)
        return runtime, 'full'

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
                    # Column-store rows (and its recovery journal) are counted
                    # by that backend; a hot journal is not an extra query.
                    if not (self.storage == 'columnar' and entry.name in
                            ('completed.sqlite', 'completed.sqlite-journal')):
                        self._entries += 1
                    if self._used > self.max_store_bytes or self._entries > self.max_entries:
                        raise CheckpointRefused('checkpoint store exceeds configured disk bounds')
            # The columnar helper is imported only when selected, before the
            # full entry check. A package that ships it has it bound already:
            # the strict context's identity walk imports every package module.
            # A package without it imports and serves 'files' unchanged, and
            # selecting 'columnar' there fails here, before any query.
            columnar = None
            if self.storage == 'columnar':
                from .compact_query_store import CompactQueryStore as columnar
            self._active = True
            self._runtime = self._check(boundary=False)
            if len(self._runtime) > MAX_BINDING//2:
                raise CheckpointRefused('execution identity metadata exceeds bounded owner')
            if columnar is not None:
                self._compact = columnar(self.directory, self.budget,
                                         self.max_store_bytes, self.max_entries)
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
        self._sources_seen = None
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
                    or hashlib.sha256(bound).digest() != bound_hash
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


# No module-level import of compact_query_store (see __enter__): that helper
# imports this module, and an import back from here formed a cycle that failed
# whenever the helper loaded first, as the sorted identity walk loads it. It
# also made every package copy that ships this companion without the helper
# unimportable, which the identity walk then (correctly) refuses.
