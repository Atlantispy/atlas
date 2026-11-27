"""Bounded, optional exact-interface workers for the private ALE workflow.

Only a source-bound cost prediction of at least two minutes opts a contact in.
Unknown or cheap contacts remain serial. A cheap exact trial eliminates current
zero certificates before spawning. At most two selected contacts are in flight;
there is no whole-mesh task/result list or persistent child allocation.
A session given a planner instead of a predictor lets that planner decide from
its own estimates before anything is funded, then screens and dispatches what
it selects through the same funding, binding, adoption and stop paths.

Inputs are immutable, digest-bound files mapped read-only by each child. Python
JSON decoding still copies. Parent wire/decoding storage and the actual child
workspace are prepaid, revocable optional leases. The original serial prefix is
always executed. Failed speculation never supplies a numerical result. Elapsed
times and outcomes kept for a caller's report never enter a receipt or record.

A batch session starts one such one-shot worker for an ordered list of exact
requests chosen by a scheduler outside this module. The worker runs the same
unchanged issuer call for each member under a ledger of exactly the bound
limits and answers all of them in one bound completion. One envelope is
charged for the batch from its launch until its last member is adopted or
dropped; a member is adopted only after its worker has exited.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
from itertools import islice
import json
import math
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import weakref

from atlas_tectonics.integration.geometry import differential_geometry as G
from atlas_tectonics.integration import resources as R
from atlas_tectonics.integration.parallel.worker_bootstrap import launch as _worker_launch
from atlas_tectonics.integration.parallel.binding import (BATCH_LIMIT, WALL_KIND, BatchBinding, JobBinding,
    OwnedBatchDispatch, OwnedDispatch, batch_worker_complete, canonical, capture_runtime,
    is_batch, VOLUME_SCHEMA)
from atlas_tectonics.integration.parallel.binding import (_BATCH_SCHEMA as BATCH_SCHEMA,
    _batch_worker_complete as _bound_batch_complete, _worker_complete)
from atlas_tectonics.integration.parallel.owner import RevocableOwner
from atlas_tectonics.integration.parallel.results import (FitWitness, MeasureHint, SlotLease,
    _owner_price, raw_capacity)
from atlas_tectonics.integration.geometry.volume_bounds import _Arena

MAX_INPUT = 2 << 20
MAX_RESULT = 1 << 20
MAX_RECEIPT = 4 << 20
PARENT_STORAGE = 64 << 20
CHILD_BASELINE = 256 << 20
SCAN_LIMIT = 64
MAX_BATCH_INPUT = 64 << 20    # encoded supports one batch may ship
BATCH_LOG = 32                # finished batches named in a session's report
SURVEY = 0.25                 # seconds between two system-wide process surveys of one batch child


def _request(support, key, name, pair, width, leaves):
    header_owner = support_header(support)
    record = header_owner.value
    return dict(schema=G.MEASURE_SCHEMA, kind='component-moving-radial-interface',
        support_id=support.support_id, interval_id=record['interval_id'],
        logical_cell_id=key, constraint_name=name,
        other_support_id=None if pair.get('other_support') is None else pair['other_support'].support_id,
        other_logical_cell_id=pair.get('other_logical_cell_id'),
        start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
        max_width_m3=G._qtext(G.W._q(width)), max_leaves=leaves)


def _call(support, other, request, budget, *, screen_only=False):
    if request.get('schema') == VOLUME_SCHEMA:
        if other is not None or screen_only:
            raise ValueError('an endpoint worker takes one support and no screening mode')
        return G.component_volume_bounds(support, request['logical_cell_id'],
            endpoint=request['endpoint'], max_width_m3=G.W._decode(request['max_width_m3']),
            max_leaves=request['max_leaves'], positive_witness=True, budget=budget)
    if request['kind'] == 'component-fixed-voxel-face':
        if other is not None:
            raise ValueError('a fixed-wall worker takes one material support')
        return G.enclose_component_wall(support, request['logical_cell_id'],
            request['axis'], request['end'],
            max_width_m3=G.W._decode(request['max_width_m3']), max_leaves=request['max_leaves'],
            budget=budget, _screen_only=screen_only)
    return G.enclose_component_interface(support, request['logical_cell_id'],
        request['constraint_name'], other_support=other,
        other_logical_cell_id=request['other_logical_cell_id'],
        max_width_m3=G.W._decode(request['max_width_m3']), max_leaves=request['max_leaves'],
        budget=budget, _screen_only=screen_only)


def _wall_request(support, key, axis, pair, width, leaves):
    header_owner = support_header(support)
    record = header_owner.value
    if pair.keys() != {'end'}:
        raise ValueError('a wall job requires exactly its end selector')
    return dict(schema=G.MEASURE_SCHEMA, kind='component-fixed-voxel-face',
        support_id=support.support_id, interval_id=record['interval_id'], logical_cell_id=key,
        axis=axis, end=pair['end'], start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
        max_width_m3=G._qtext(G.W._q(width)), max_leaves=leaves)


def _support(raw, identity, budget):
    # Private transport of a parent's issued object, not a public restore. identity None: the batch route, whose
    # parent wrote these bytes in this run under their digest name; the one-job route hashes them here.
    if not 0 < len(raw) <= MAX_INPUT or identity is not None and hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError('complete issued support bytes differ')
    value = G._issue(G.DifferentialSupport, json.loads(raw), budget)
    if value._json != raw:
        raise ValueError('noncanonical support bytes')
    if identity is not None:
        object.__setattr__(value, '_support_id', identity)
    return value


def _screen_support(support, budget):
    # A separately funded handle over the already issued immutable bytes.
    raw = support._json
    if not 0 < len(raw) <= MAX_INPUT:
        raise ValueError('complete issued support bytes differ')
    lease = budget.reserve(8192+len(raw), category='differential-geometry-retained')
    lease.__enter__()
    try:
        result = object.__new__(G.DifferentialSupport)
        object.__setattr__(result, '_json', raw)
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_support_id', support.support_id)
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise


def transport(support):
    """(support id, encoded bytes) of an issued support that fits the optional transport, else None.

    The size filters of the predictor route, unchanged.
    """
    if type(support) is CompactSupport:
        return compact_transport(support, MAX_INPUT, PARENT_STORAGE)
    raw = support._json
    if len(raw) <= MAX_INPUT and support.decoded_capacity+65536+4*len(raw) <= PARENT_STORAGE//4:
        return support.support_id, len(raw)
    return None


def _mapped_read(path, limit):
    with Path(path).open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        if not 0 < size <= limit:
            raise ValueError('bounded transport file size differs')
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            return mapped[:]


def _replace(source, target, tries=50, pause=0.02):
    # Windows refuses to replace a file that another process holds open, and
    # the parent's monitor reads resource.json every 50 ms. Such a refusal is
    # transient: retry for about a second before reporting it.
    for attempt in range(tries):
        try:
            return os.replace(source, target)
        except PermissionError:
            if attempt+1 >= tries:
                raise
            time.sleep(pause)


def _resource_report(directory, process, body_seconds=None, ledger_peak=None, *, batch=None):
    memory = process.memory_info()
    report = dict(pid=process.pid, create_time=process.create_time(),
        rss=memory.rss, peak_rss=getattr(memory, 'peak_wset', memory.rss))
    if batch is not None:
        report['batch'] = batch
    if body_seconds is not None:
        # Scheduling observation for the parent's profile only. It is outside
        # the four-key receipt and is never compared with a result.
        report['body_seconds'] = body_seconds
    if ledger_peak is not None:
        # The largest accounted peak of a batch's child ledgers: for the report only.
        report['ledger_peak'] = ledger_peak
    with (directory/'resource-next.json').open('wb') as stream:
        stream.write(canonical(report))
    _replace(directory/'resource-next.json', directory/'resource.json')


def worker_main(directory):
    """One trusted one-shot subprocess, no subprocesses or arbitrary callables.

    Strict or packaged release (decision 3): this process decides its own mode from the same
    payload, its first capture is its own full boundary, and worker_complete compares its live
    identity with the parent's binding before and after the body.
    """
    from atlas_tectonics.integration.reuse import ExecutionContext, execution_mode
    if execution_mode() not in ('strict', 'release'):
        raise RuntimeError('worker requires strict or packaged release execution')
    directory = Path(directory)
    import psutil
    process = psutil.Process()
    # The START report identifies this worker to its parent: it must succeed.
    _resource_report(directory, process)
    if (directory/'kept').is_file():           # written by the parent before the launch
        return _kept_worker(directory, process)
    binding_bytes = _mapped_read(directory/'binding.json', MAX_RECEIPT)
    record = json.loads(binding_bytes)
    if type(record) is dict and record.get('schema') == BATCH_SCHEMA:
        # This entry is the private owned file/launch relationship. Raw byte APIs
        # do not obtain it by presenting a schema or a seconds field.
        if 'batch_seconds' in record:
            return _owned_batch_worker(directory, process, binding_bytes, record)
        return _batch_worker(directory, process, binding_bytes, _record=record)
    binding = JobBinding._read(binding_bytes, record)
    request = record['request']
    inputs = {}
    for name, identity in (('support', request['support_id']), ('other', request.get('other_support_id'))):
        if identity is None and name == 'other':
            continue
        if (type(identity) is not str or len(identity) != 64
                or any(c not in '0123456789abcdef' for c in identity)):
            raise ValueError('complete support digest required before resolving input')
        inputs[name] = _mapped_read(directory.parent/'inputs'/(identity+'.json'), MAX_INPUT)
    child_budget = R.WorkBudget(**record['child_budget'])
    # Reissued support retention is inside E too, making child admission
    # stricter than the parent's already-retained inputs, never more lenient.
    supports = [_support(inputs['support'], request['support_id'], child_budget)]
    other = None if 'other' not in inputs else _support(inputs['other'], request['other_support_id'], child_budget)
    body = []
    with ExecutionContext('reference') as context:
        def run(actual_budget):
            begun = time.perf_counter()
            result = _call(supports[0], other, request, actual_budget)
            body.append(time.perf_counter()-begun)
            if len(result._json) > MAX_RESULT:
                raise ValueError('result exceeds optional wire envelope')
            return result._json
        receipt = _worker_complete(binding, context=context,
            request=request,
            child_budget=child_budget, run=run, record=record)
        if len(receipt) > MAX_RECEIPT:
            raise ValueError('receipt exceeds optional wire envelope')
        with (directory/'result.json').open('xb') as stream:
            stream.write(receipt)
    try:
        _resource_report(directory, process, body[0] if body else None)
    except Exception:
        # The receipt is complete and verified. A late resource report proves
        # nothing more and must not turn a finished result into a decline.
        pass


def _batch_worker(directory, process, binding_bytes, *, _record=None):
    """worker_main for a batch binding: every member through the unchanged issuer call.

    Members that share their supports run on one ledger of exactly the bound
    limits, as empty before each member as a fresh one; otherwise the next
    member gets a new ledger. A fixed wall the exact prefix decides is
    answered 'decided': the parent's own prefix issues it and never claims.
    A member the child ledger or the issuer refuses is answered 'declined'
    and the parent's serial body runs for it; any other failure ends the
    worker without a completion.
    """
    binding, record = BatchBinding._read(binding_bytes, _record)
    return _batch_body(directory, process, binding, record)


def _owned_requests(record):
    # The mapped-file allocation boundary still bounds count before indexing/input opens.
    # Field/kind/token facts come from the concrete producer, not another sweep here.
    requests = record['requests']
    if type(requests) is not list or not 1 <= len(requests) <= BATCH_LIMIT:
        raise ValueError('bounded nonempty owned batch required')
    return requests


def _owned_batch_worker(directory, process, binding_bytes, record):
    _owned_requests(record)
    return _batch_body(directory, process, BatchBinding._owned_bytes(binding_bytes), record)


def _batch_body(directory, process, binding, record):
    from atlas_tectonics.integration.reuse import ExecutionContext
    requests, binding_bytes = record['requests'], binding.encoded
    if requests[0].get('schema') == 'atlas.private.pressure-wall.r1':
        # Pressure P1: pressure walls load and answer their own digest-checked inputs.
        from atlas_tectonics.integration.coupling.pressure_walls import batch_worker
        return batch_worker(directory, process, binding_bytes, requests)
    inputs = _read_inputs(directory, requests)
    observed = dict(body=0.0, peak=0)
    with ExecutionContext('reference') as context:
        _complete(directory, binding_bytes, requests, inputs, context, observed,
                  batch_seconds=record.get('batch_seconds'), _binding=binding, _record=record)
    try:
        _resource_report(directory, process, observed['body'], observed['peak'])
    except Exception:
        pass    # as for a one-job worker: the completion is already verified


def _read_inputs(directory, requests):
    """The batch's encoded supports, each read once, within the transport envelope."""
    inputs, size = {}, 0
    for request in requests:
        for identity in (request['support_id'], request.get('other_support_id')):
            if identity is None or identity in inputs:
                continue
            if (type(identity) is not str or len(identity) != 64
                    or any(c not in '0123456789abcdef' for c in identity)):
                raise ValueError('complete support digest required before resolving input')
            raw = inputs[identity] = _mapped_read(directory/'inputs'/(identity+'.json'), MAX_INPUT)
            size += len(raw)
            if size > MAX_BATCH_INPUT:
                raise ValueError('batch inputs exceed the optional transport envelope')
    return inputs


def _complete(directory, binding_bytes, requests, inputs, context, observed, *, batch_seconds=None,
              _binding=None, _record=None):
    """Every member through the unchanged issuer call between the two binding checks; result.json written."""
    wall = requests[0].get('kind') == WALL_KIND

    def run(new_ledger):
        return answer(new_ledger)

    def answer(new_ledger):
        # The completion repeats the binding; each result is carried as one JSON string.
        answers, held, room = [], None, MAX_RECEIPT-2*len(binding_bytes)-65536
        if requests[0].get('schema') == VOLUME_SCHEMA:
            from atlas_tectonics.integration.geometry.component_volume_parallel import component_answers
            return component_answers(requests, inputs, new_ledger, room, observed)
        for index, request in enumerate(requests):
            if not wall and index and batch_seconds is not None and observed['body'] >= batch_seconds:
                # Nothing of this suffix has started, including support/ledger preparation.
                answers.extend(['returned']*(len(requests)-index))
                break
            pair = request['support_id'], request.get('other_support_id')
            try:
                reuse = held is not None and held[0] == pair
                if reuse and held[1].reserved_bytes != held[4]:
                    gc.collect()
                    reuse = held[1].reserved_bytes == held[4]
                if not reuse:
                    if held is not None:
                        observed['peak'] = max(observed['peak'], held[1].statistics()['peak_reserved_bytes'])
                    held = None
                    ledger = new_ledger()
                    # Reissued support retention is inside E too, as for a one-job worker.
                    support = _support(inputs[pair[0]], None, ledger)    # bound by the first check
                    other = None if pair[1] is None else _support(inputs[pair[1]], None, ledger)
                    held = pair, ledger, support, other, ledger.reserved_bytes
                begun = time.perf_counter()
                try:
                    raw = _call(held[2], held[3], request, held[1])._json
                except ValueError:
                    if not wall and batch_seconds is not None:
                        observed['body'] += time.perf_counter()-begun
                    raise
                observed['body'] += time.perf_counter()-begun
                if wall and json.loads(raw).keys() & {'exact_zero_normal_flux', 'exact_zero_wall_measure'}:
                    answers.append('decided')
                elif len(raw) > MAX_RESULT or 2*len(raw)+256 > room:
                    answers.append('declined')    # the bounded completion has no room for it
                else:
                    answers.append(raw)
                    room -= 2*len(raw)+256
            except ValueError:
                answers.append('declined')
                held = None
        if held is not None:
            observed['peak'] = max(observed['peak'], held[1].statistics()['peak_reserved_bytes'])
        return answers

    if _binding is None:
        receipt = batch_worker_complete(binding_bytes, context=context,
            requests=requests, run=run)
    else:
        receipt = _bound_batch_complete(_binding, _record, context=context,
            requests=requests, run=run)
    if len(receipt) > MAX_RECEIPT:
        raise ValueError('receipt exceeds optional wire envelope')
    with (directory/'result.json').open('xb') as stream:
        stream.write(receipt)


def _kept_worker(home, process):
    """One context for the worker's life; one batch folder per line on standard input.

    Each batch starts after garbage collection and checks its binding at both
    ends. Consecutive wall or interface members can reuse a settled ledger for
    the same support pair. A batch is finished only when its
    result.json is closed and then its done file created. Nothing is caught:
    an exception leaves the loop, the context's exit runs and the process
    exits non-zero. The context's closing check runs once, at the end.
    """
    from atlas_tectonics.integration.reuse import ExecutionContext
    with ExecutionContext('reference') as context:
        for line in sys.stdin.buffer:          # end of input: the parent has finished with this worker, or is gone
            directory = Path(line.rstrip(b'\r\n').decode('utf8')).resolve()
            gc.collect()
            binding_bytes = _mapped_read(directory/'binding.json', MAX_RECEIPT)
            record = json.loads(binding_bytes)
            if type(record) is dict and 'batch_seconds' in record:
                requests = _owned_requests(record)
                binding = BatchBinding._owned_bytes(binding_bytes)
            else:
                binding, record = BatchBinding._read(binding_bytes, record)
                requests = record['requests']
            if requests[0].get('schema') == 'atlas.private.pressure-wall.r1':
                raise ValueError('a kept worker does not answer pressure walls')
            inputs = _read_inputs(directory, requests)
            observed = dict(body=0.0, peak=0)
            _complete(directory, binding_bytes, requests, inputs, context, observed,
                      batch_seconds=record.get('batch_seconds'), _binding=binding, _record=record)
            # V-1: the figure the recycle rule reads is taken after the batch is dropped and collected.
            del binding_bytes, requests, inputs, record, binding
            gc.collect()
            try:
                _resource_report(home, process, observed['body'], observed['peak'], batch=directory.name)
            except Exception:
                pass    # the completion is already verified
            with (directory/'done').open('xb'):
                pass


class _Child:
    served = False    # a one-shot child is adopted only after its exit is confirmed

    def __init__(self, directory, deadline, rss_limit, interval=None, kept=False):
        self.directory, self.deadline, self.rss_limit = directory, deadline, rss_limit
        # A kept worker serves one batch at a time: the session sets batch and baseline.
        self.kept, self.batch, self.baseline, self.rss, self.bad_end = kept, None, None, None, None
        self._served_batch = None
        self.stop_seconds = 0.0
        # None surveys the whole system in every round, as the one-job routes always did.
        self.interval, self._surveyed = interval, None
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.process = None
        self.cancelled = False
        self.exited = False
        self.peak_rss = 0
        # Scheduling observations only: launch-to-return seconds measured here
        # and the body seconds the worker reports. Neither is ever evidence.
        self.elapsed = self.body_seconds = self.ledger_peak = None
        self._owned = {}
        self._worker_identity = None
        self._launched_at = None
        # A Windows venv executable can only be the small redirector. Its
        # exit alone says nothing about the real interpreter it launched.
        base = getattr(sys, '_base_executable', sys.executable)
        self._redirected = (sys.platform == 'win32' and
            os.path.normcase(os.path.abspath(base)) != os.path.normcase(os.path.abspath(sys.executable)))

    def _remember(self, process):
        import psutil
        try:
            identity = process.pid, process.create_time()
            if process.is_running():
                self._owned[identity] = process
                return identity
        except psutil.NoSuchProcess:
            pass
        return None

    def _alive(self, identity, process):
        import psutil
        try:
            # is_running checks reuse of this Process object's original PID;
            # create_time also binds the identity saved by this owner.
            # Windows psutil.status() only distinguishes running/suspended,
            # both of which are live here. Its system-wide thread census adds
            # no zombie test on Windows. Keep the status check on POSIX, where
            # is_running() deliberately includes zombies. Never cache liveness.
            return (process.is_running() and process.create_time() == identity[1]
                    and (sys.platform == 'win32' or process.status() != psutil.STATUS_ZOMBIE))
        except psutil.NoSuchProcess:
            return False

    def _worker_record(self):
        import psutil
        try:
            with (self.directory/'resource.json').open('rb') as stream:
                raw = stream.read(4097)
        except OSError:
            # Missing, or the worker is replacing it at this moment (a Windows
            # sharing violation). Like a missing file, that proves nothing.
            return
        if not raw or len(raw) > 4096:
            return
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError):
            return  # Startup writing may still be in progress; this proves nothing.
        if type(record) is not dict:
            return
        pid, created = record.get('pid'), record.get('create_time')
        if (type(pid) is not int or pid <= 0 or type(created) not in (int, float)
                or not math.isfinite(created) or created <= 0
                or self._launched_at is None or created < self._launched_at-1
                or created > time.time()+1):
            return
        identity = pid, created
        if self._worker_identity is not None and self._worker_identity != identity:
            raise RuntimeError('owned worker identity changed')
        try:
            process = psutil.Process(pid)
            if process.create_time() != created:
                # The named worker exited and its PID was reused. Never add
                # or signal the unrelated replacement.
                self._worker_identity = identity
                return
            command = process.cmdline()
            if (len(command) < 3 or command[-3:-1] !=
                    ['-m', 'atlas_tectonics.integration.parallel.worker']
                    or os.path.normcase(os.path.abspath(command[-1])) !=
                    os.path.normcase(os.path.abspath(str(self.directory)))):
                raise RuntimeError('resource identity is not the owned worker command')
            self._remember(process)
        except psutil.NoSuchProcess:
            pass
        self._worker_identity = identity
        reported = record.get('peak_rss')
        if type(reported) is int and reported >= 0:
            self.peak_rss = max(self.peak_rss, reported)
        rss = record.get('rss')
        if (type(rss) is int and rss >= 0
                and (not self.kept or record.get('batch') == self._served_batch)):
            self.rss = rss    # the recycle rule's input, from this batch only
        body = record.get('body_seconds')
        # The range alone refuses NaN and infinity, and compares an integer
        # beyond float range exactly where math.isfinite would raise on it.
        if type(body) in (int, float) and 0 <= body <= 1e9:
            self.body_seconds = float(body)
        peak = record.get('ledger_peak')
        if type(peak) is int and 0 <= peak < 1 << 62:
            self.ledger_peak = peak

    def _discover(self):
        import psutil
        if self.process is not None and self.process.poll() is None:
            try:
                self._remember(psutil.Process(self.process.pid))
            except psutil.NoSuchProcess:
                pass
        covered = set()
        for identity, process in tuple(self._owned.items()):
            if identity in covered or not self._alive(identity, process):
                continue
            try:
                descendants = process.children(recursive=True)
            except psutil.NoSuchProcess:
                continue
            for descendant in descendants:
                try:
                    candidate = descendant.pid, descendant.create_time()
                    # Established ownership survives reparenting; its exact
                    # PID/create-time still has to be live in _remember.
                    # A new identity needs a fresh verified ancestry chain.
                    if candidate not in self._owned and not self._descends_from(descendant, identity):
                        continue
                    remembered = self._remember(descendant)
                    if remembered is not None:
                        # children(recursive=True) already surveyed this
                        # subtree in this round. Orphaned tracked roots that
                        # were absent from that census are surveyed separately.
                        covered.add(remembered)
                except psutil.NoSuchProcess:
                    pass
        # Recovers the trusted one-shot worker when its redirector exited
        # before enumeration. A missing/malformed record is never exit proof.
        self._worker_record()
        return [(identity, process) for identity, process in self._owned.items()
                if self._alive(identity, process)]

    @staticmethod
    def _descends_from(process, identity):
        # parents() constructs the COMPLETE ancestry before a caller can
        # stop at its owned ancestor. On Windows each extra parent asks for
        # another system-wide process snapshot. Walk only the required chain;
        # psutil.parent() retains its PID-reuse and creation-time checks.
        seen = set()
        parent = process.parent()
        while parent is not None:
            candidate = parent.pid, parent.create_time()
            if candidate == identity:
                return True
            if candidate in seen:
                return False
            seen.add(candidate)
            parent = parent.parent()
        return False

    def _worker_known(self):
        return (self._worker_identity is not None or not self._redirected or
                any(identity[0] != self.process.pid for identity in self._owned))

    def _survey(self, process):
        """(live owned processes, whether the whole system was asked for them).

        A system-wide census costs the parent far more than measuring the
        processes it already owns. With an interval, a child whose worker is
        known and whose launcher still runs is surveyed only that often; in
        between, the owned processes are checked and measured every round, so
        the memory guard and the deadline act as promptly as before. A new
        descendant is found at the next survey, and nothing is called finished
        without one.
        """
        if (self.interval is not None and self._surveyed is not None and self._worker_known()
                and process.poll() is None and time.monotonic()-self._surveyed < self.interval):
            return [(identity, owned) for identity, owned in self._owned.items()
                    if self._alive(identity, owned)], False
        live = self._discover()
        if self.interval is not None:
            self._surveyed = time.monotonic()
        return live, True

    def run(self, binding_bytes):
        # OwnedDispatch supplies exactly its bound bytes. Never attach a
        # foreign Future or accept an arbitrary completion file.
        if (self.directory/'binding.json').read_bytes() != binding_bytes:
            raise ValueError('dispatch file changed before launch')
        command, env = _worker_launch(self.directory)
        started = time.monotonic()
        launched = time.perf_counter()
        process = self._popen(command, env, subprocess.DEVNULL)
        try:
            while True:
                with self.lock:
                    live, whole = self._measure(process)
                    finished = whole and process.poll() is not None and not live and self._worker_known()
                    if process.poll() is not None and not live and not self._worker_known():
                        raise RuntimeError('optional worker identity unconfirmed after redirector exit')
                if finished:
                    break
                if self.peak_rss > self.rss_limit or time.monotonic()-started > self.deadline:
                    raise RuntimeError('optional child resource guard reached')
                time.sleep(0.05)
            if process.returncode:
                raise RuntimeError('optional exact child declined: '+self._stderr())
            return _mapped_read(self.directory/'result.json', MAX_RECEIPT)
        finally:
            self.elapsed = time.perf_counter()-launched
            self.stop()

    def _popen(self, command, env, stdin):
        with self.lock:
            if self.cancelled:
                raise RuntimeError('optional child cancelled before launch')
            self._launched_at = time.time()
            with (self.directory/'stderr.txt').open('wb') as errors:
                self.process = subprocess.Popen(
                    command,
                    env=env, stdin=stdin, stdout=subprocess.DEVNULL, stderr=errors,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return self.process

    def _measure(self, process):
        # One monitoring round, under the lock: (live owned processes, whether surveyed); peak_rss updated.
        import psutil
        live, whole = self._survey(process)
        rss = 0
        for identity, monitor in live:
            try:
                if self._alive(identity, monitor):
                    rss += monitor.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        self.peak_rss = max(self.peak_rss, rss)
        return live, whole

    def _stderr(self):
        with (self.directory/'stderr.txt').open('rb') as errors:
            return errors.read(4096).decode('utf8', errors='replace')

    def serve(self, path, binding_bytes):
        """A kept worker's next batch: its result once its done file is seen.

        The launch, if this is the worker's first batch; the folder's line;
        then the one-shot loop's memory and deadline guards, counted for this
        batch. A launcher that has exited, or no live owned process, before
        the done file is a failure. On any exception the worker is stopped.
        """
        path = Path(path)
        self._served_batch = path.name
        if (path/'binding.json').read_bytes() != binding_bytes:
            raise ValueError('dispatch file changed before launch')
        started, launched = time.monotonic(), time.perf_counter()
        self.peak_rss, self.rss = 0, None
        self.body_seconds = self.ledger_peak = None
        try:
            if self.process is None:
                command, env = _worker_launch(self.directory)
                self._popen(command, env, subprocess.PIPE)
            process = self.process
            with self.lock:
                if self.cancelled:
                    raise RuntimeError('optional child cancelled before launch')
                process.stdin.write(str(path.absolute()).encode('utf8')+b'\n')
                process.stdin.flush()
            done = path/'done'
            while True:
                with self.lock:
                    live, whole = self._measure(process)
                    finished = done.exists() and self._worker_known()
                    if not finished and (process.poll() is not None or whole and not live and self._worker_known()):
                        raise RuntimeError('kept worker ended before its batch was done: '+self._stderr())
                if finished:
                    break
                if self.peak_rss > self.rss_limit or time.monotonic()-started > self.deadline:
                    raise RuntimeError('optional child resource guard reached')
                time.sleep(0.05)
            with self.lock:
                self._worker_record()
            return _mapped_read(path/'result.json', MAX_RECEIPT)
        except BaseException:
            self.stop()
            raise
        finally:
            self.elapsed = time.perf_counter()-launched

    def stop(self):
        begun = time.perf_counter()
        try:
            if self.kept and self.batch is None:
                self._close_input()
            self._halt()
        finally:
            self.stop_seconds += time.perf_counter()-begun

    def _close_input(self):
        # An idle kept worker leaves its loop by itself, so its context's closing check runs (design 4.1).
        with self.lock:
            process = self.process
            if process is None or self.exited or process.stdin is None or process.stdin.closed:
                return
            try:
                process.stdin.close()
                code = process.wait(10)
            except (OSError, subprocess.TimeoutExpired):
                return    # today's terminate and kill follow
            if code:
                self.bad_end = 'kept worker ended with exit %s: %s' % (code, self._stderr())

    def _halt(self):
        import psutil
        # Lock closes queued-launch and monitoring races. Each phase has one
        # ten-second bound for the entire tracked set, not ten seconds per PID.
        with self.lock:
            self.cancelled = True
            process = self.process
            if process is None or self.exited:
                return
            failure = None
            for operation in ('terminate', 'kill'):
                deadline = time.monotonic()+10
                signalled = set()
                root_signalled = False
                while True:
                    try:
                        self._discover()
                    except (psutil.Error, OSError, ValueError, RuntimeError) as error:
                        failure = failure or error
                    live = []
                    for identity, owned in tuple(self._owned.items()):
                        try:
                            if self._alive(identity, owned):
                                live.append((identity, owned))
                        except (psutil.Error, OSError) as error:
                            failure = failure or error
                    # The Popen handle belongs to this launch even if process
                    # discovery failed. Never signal a PID merely from a file.
                    if process.poll() is None and not root_signalled:
                        try:
                            getattr(process, operation)()
                            root_signalled = True
                        except (OSError, psutil.Error) as error:
                            failure = failure or error
                    for identity, owned in live:
                        if identity in signalled or identity[0] == process.pid:
                            continue
                        try:
                            if self._alive(identity, owned):
                                getattr(owned, operation)()
                            signalled.add(identity)
                        except psutil.NoSuchProcess:
                            pass
                        except (psutil.Error, OSError) as error:
                            failure = failure or error
                    if process.poll() is not None and not live:
                        if failure is not None:
                            raise RuntimeError('optional child tree shutdown unconfirmed') from failure
                        if self._worker_known():
                            self.exited = True
                            return
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
            raise RuntimeError('optional child tree shutdown unconfirmed') from failure


class InterfaceParallelSession:
    """Optional ALE session with an explicit source-bound cost predictor.

    expected_seconds(request, execution_identity) returns a current prediction
    or None. Old profiles bound to other code must return None, not be silently
    reused. Context and budget belong to the workflow caller. max_width_m3 must
    be its actual per-stream bound. Unknown work is never forced parallel.

    planner replaces the predictor for automatic selection. It supplies
    lookahead, screen_bytes and screen_units; candidates(jobs) returning the
    positions worth an exact screen after ITS unfunded decision; context()
    for the strict execution context; and choose(screens) returning the
    positions to dispatch and their timeout. plan, outcomes and waits report
    what happened to the caller; none of them is issued state.
    """
    _make_request = staticmethod(_request)

    def __init__(self, *, budget, context, max_width_m3, max_leaves,
                 expected_seconds=None, minimum_seconds=120, child_bytes=128 << 20,
                 predicate_units=1 << 34, timeout_seconds=1800, planner=None):
        if type(budget) is not R.WorkBudget or type(child_bytes) is not int or child_bytes <= 0:
            raise ValueError('plain budget and positive worker envelope required')
        if (not math.isfinite(minimum_seconds) or minimum_seconds < 0 or
                not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError('finite positive timing policy required')
        if planner is not None and expected_seconds is not None:
            raise ValueError('a session takes a planner or a predictor, not both')
        self.budget, self.context = budget, context
        self.width, self.leaves = max_width_m3, max_leaves
        self.predict, self.minimum = expected_seconds, minimum_seconds
        self.planner = planner
        self.child_bytes = child_bytes
        self.units = None if budget._predicate_work is None else predicate_units
        self.timeout = timeout_seconds
        self.owner = self.storage = self.pool = self.directory = None
        self.jobs = {}
        self.prepared = self.closed = False
        self.stats = dict(scanned=0, cheap=0, started=0, adopted=0, declined=0, peak_child_rss=0)
        self.last_error = None
        self.plan, self.outcomes, self.waits, self._events = {}, [], 0, []

    def prepare(self, jobs):
        if self.prepared or self.closed:
            raise RuntimeError('one prepare per optional ALE session')
        self.prepared = True
        if self.planner is not None:
            return self._prepare_automatic(jobs)
        if self.predict is None:
            return
        # All request/source/transport bookkeeping is optional and prepaid.
        self.storage = SlotLease.attempt(R, self.budget, PARENT_STORAGE)
        if self.storage is None:
            return
        try:
            identity = self._open_owner()
            if identity is None:
                return
            owner = self.owner
            for index, (support, key, name, pair) in enumerate(jobs):
                with owner.condition:
                    if owner.state != 'ACTIVE' or index >= SCAN_LIMIT or len(self.jobs) >= 2:
                        break
                    self.stats['scanned'] += 1
                    other = pair.get('other_support')
                    if transport(support) is None or other is not None and transport(other) is None:
                        continue
                    request = self._make_request(support, key, name, pair, self.width, self.leaves)
                    cost = self.predict(request, identity)
                    if (type(cost) not in (int, float) or not math.isfinite(cost)
                            or cost < self.minimum):
                        continue
                    if self._cheap(support, other, request):
                        self.stats['cheap'] += 1
                        continue
                    self._dispatch(support, other, request)
            return
        except Exception as error:
            self.last_error = str(error)[:4096]
        # Exception/decoded descendants have left their handling scope before
        # storage is released. A failed shutdown itself is never suppressed.
        self.close()

    def _open_owner(self):
        """Runtime capture, owner lease, registered owner and directory, in order.

        Only after the PARENT_STORAGE lease. Returns the execution identity,
        or None when the owner lease was refused (the session is then closed)
        or the registered owner is no longer ACTIVE (nothing more acquired).
        """
        identity = capture_runtime(self.context)['execution_identity']
        # The caller owns the policy/session handle. Registered revocation
        # metadata remains separately funded until that owner actually
        # dies, including a held shutdown traceback. It is not confused
        # with the much larger temporary input/receipt graph below.
        owner_lease = SlotLease.attempt(R, self.budget, _owner_price)
        if owner_lease is None:
            self.close()
            return None
        try:
            owner = RevocableOwner((self.budget,), self._stop)
            weakref.finalize(owner, owner_lease.close)
        except BaseException:
            owner_lease.close()
            raise
        # The close path must know this owner before registration can succeed
        # or be interrupted. An owner whose entry failed is safe to close.
        self.owner = owner
        owner.__enter__()
        with owner.condition:
            if owner.state != 'ACTIVE':
                return None
            self.directory = tempfile.TemporaryDirectory(prefix='atlas-interfaces-')
            (Path(self.directory.name)/'inputs').mkdir()
        return identity

    def _prepare_automatic(self, jobs):
        """Planner route: decide from estimates first, fund only a likely plan.

        The planner's own decision uses no lease, context, decode or
        directory, so a serial answer leaves the ledger untouched. A likely
        plan is funded exactly as the predictor route is. Whenever nothing is
        in flight afterwards, every optional admission is returned at once
        and not held to the end of the enclosure.
        """
        planner, plan = self.planner, self.plan
        try:
            scanned = list(islice(jobs, max(0, min(SCAN_LIMIT, planner.lookahead))))
            self.stats['scanned'] = len(scanned)
            wanted = planner.candidates(scanned)
            if wanted:
                self.storage = SlotLease.attempt(R, self.budget, PARENT_STORAGE)
                if self.storage is None:
                    plan['funding'] = 'parent storage refused'
                else:
                    self.context = planner.context()
                    if self._open_owner() is None:
                        plan['funding'] = 'owner lease refused' if self.closed else 'owner revoked'
                    else:
                        self._select(scanned, wanted)
                        if self.jobs:
                            return
        except Exception as error:
            self.last_error = str(error)[:4096]
        # As above: a failed shutdown is never suppressed.
        self.close()

    def _select(self, scanned, wanted):
        planner, plan, owner = self.planner, self.plan, self.owner
        screens, ready = plan.setdefault('screens', {}), {}
        begun = time.perf_counter()
        for index in wanted:
            with owner.condition:
                if owner.state != 'ACTIVE':
                    break
                support, key, name, pair = scanned[index]
                other = pair.get('other_support')
                # The size filters of the predictor route, unchanged: transport() is that predicate.
                if transport(support) is None or other is not None and transport(other) is None:
                    screens[index] = 'oversize'
                    continue
                request = self._make_request(support, key, name, pair, self.width, self.leaves)
                screens[index] = self._screen(support, other, request,
                    scratch_bytes=planner.screen_bytes, scratch_units=planner.screen_units)
                if screens[index] == 'integrator':
                    ready[index] = support, other, request
                else:
                    self.stats['cheap'] += 1
        plan['screen_seconds'] = time.perf_counter()-begun
        selected, timeout = planner.choose(screens)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('finite positive plan timeout required')
        # Never beyond the ceiling this session was built with.
        self.timeout = plan['timeout_seconds'] = min(self.timeout, timeout)
        for index in [index for index in selected if index in ready][:2]:
            with owner.condition:
                if owner.state != 'ACTIVE':
                    plan['funding'] = 'owner revoked'
                    break
                started = self.stats['started']
                self._dispatch(*ready[index])
                if self.stats['started'] == started:
                    # _dispatch declines silently when the worker envelope,
                    # its baseline or its result slot is refused.
                    plan.setdefault('refused', []).append(index)
                    continue
                job = self.jobs[canonical(ready[index][2])]
                job['index'] = index
                self._events.append(job['child'].done)
                plan.setdefault('started', []).append(index)

    def _screen(self, support, other, request, *, scratch_bytes, scratch_units):
        """One exact shortcut screen: 'integrator', 'decided' or 'refused'.

        No parent mandatory geometry call. The scratch owner is a private
        root inside already paid bookkeeping. 'decided' means an exact rule
        issued the measure. 'refused' means the scratch budget or a
        validation refused: that proves nothing and the contact stays serial.
        """
        scratch = R.WorkBudget(scratch_bytes, max_predicate_work_units=scratch_units)
        try:
            support, other = as_native(support), as_native(other)
            local = _screen_support(support, scratch)
            neighbour = None if other is None else _screen_support(other, scratch)
            if _call(local, neighbour, request, scratch, screen_only=True) is None:
                return 'integrator'
            return 'decided'
        except (ValueError, TypeError, RuntimeError, OverflowError):
            return 'refused'

    def _cheap(self, support, other, request):
        # Only a completed exact shortcut screen that reaches the integrator
        # selects; malformed/unsupported/refused inputs remain serial.
        return self._screen(support, other, request, scratch_bytes=2 << 20, scratch_units=8192) != 'integrator'

    def _dispatch(self, support, other, request):
        begun = time.perf_counter()    # the parent's seconds for this request, part of its hand-over
        with self.owner.condition:
            if self.owner.state != 'ACTIVE':
                return
            fit = FitWitness.attempt(R, self.budget, self.child_bytes, self.units)
            if fit is None:
                return
            baseline = slot = None
            try:
                baseline = SlotLease.attempt(R, self.budget, CHILD_BASELINE)
                # The wire graph has its separate parent allowance. Fund only
                # the scanner's fixed slot here, then its actual received size,
                # not the maximum permitted result for every in-flight job.
                slot = SlotLease.attempt(R, self.budget, raw_capacity(0))
                if baseline is None or slot is None:
                    fit.release()
                    if baseline is not None:
                        baseline.close()
                    if slot is not None:
                        slot.close()
                    return
                inputs = InputMap(MAX_INPUT, PARENT_STORAGE)
                inputs.add('support', support)
                input_digests = {'support': support.support_id}
                if other is not None:
                    inputs.add('other', other)
                    input_digests['other'] = other.support_id
                binding = JobBinding.create(request=request, context=self.context,
                    child_bytes=self.child_bytes, predicate_units=self.units)
                hint = MeasureHint(slot, max_payload=MAX_RESULT, request=request,
                    binding=binding.record(), fit=fit)
                path = Path(self.directory.name)/str(len(self.jobs))
                path.mkdir()
                # One physical encoded file per distinct input in this session.
                # Multiple workers map the same read-only pages; each still
                # owns its JSON decoding. No whole-world input copy is made.
                for name, raw in inputs.items():
                    input_path = Path(self.directory.name)/'inputs'/(input_digests[name]+'.json')
                    try:
                        with input_path.open('xb') as stream:
                            stream.write(raw)
                    except FileExistsError:
                        pass  # child's exact digest verification remains required
                with (path/'binding.json').open('xb') as stream:
                    stream.write(binding.encoded)
                child = _Child(path, self.timeout, CHILD_BASELINE+self.child_bytes)
                dispatch = OwnedDispatch(binding)
                token = canonical(request)
                if token in self.jobs:
                    raise ValueError('duplicate optional interface request')
                job = dict(fit=fit, baseline=baseline, hint=hint, dispatch=dispatch,
                    child=child, binding=binding, request=request)
                self.jobs[token] = job
                if self.pool is None:
                    self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='atlas-interface')
                dispatch.submit(self.pool, child.run)
                dispatch._future.add_done_callback(lambda _future, event=child.done: event.set())
                self.stats['started'] += 1
                job['dispatch_seconds'] = time.perf_counter()-begun
            except BaseException:
                # If ownership reached self.jobs, _stop confirms child exit.
                if not any(j['fit'] is fit for j in self.jobs.values()):
                    fit.release()
                    if baseline is not None:
                        baseline.close()
                    if slot is not None:
                        slot.close()
                raise

    def claim(self, request, budget):
        if self.owner is None or self.closed or budget is not self.budget:
            return None
        key = canonical(request)
        owner = self.owner
        while True:
            event = None
            with owner.condition:
                if owner.state != 'ACTIVE':
                    return None
                job = self.jobs.get(key)
                if job is None or job.get('consumed'):
                    return None
                future = job['dispatch']._future
                if future is not None and not future.done():
                    event = job['child'].done
                else:
                    job['consumed'] = True
                    result = self._claim_ready(job, request, budget)
                    if result is not None:
                        return result
                # Waiting retains only the small caller-owned event, not the
                # job/Future/receipt graph that revocation may free meanwhile.
                job = future = None
            if event is None:
                owner.revoke()
                return None
            event.wait(1)
            self.waits += 1
            self._heartbeat()

    def _heartbeat(self):
        # One zero-cost call through _Arena.work on a throwaway root budget.
        # Nothing is charged to the workflow, but return hooks that a private
        # driver keeps on that function (cancellation, RSS and RAM floor) go
        # on firing while this thread only waits. A BaseException raised
        # there propagates; the caller's close() then stops the children.
        try:
            with _Arena(R.WorkBudget(1 << 16, max_predicate_work_units=1)) as arena:
                arena.work(0)
        except Exception:
            pass

    def busy(self):
        """Scheduling hint: is a child started by the planner route still running?"""
        return any(not event.is_set() for event in self._events)

    def _outcome(self, job, adopted):
        # One scheduling observation per job for the caller's report. Jobs
        # met at stop time may be incomplete: every read here is optional.
        if job.get('observed') or len(self.outcomes) >= 2:
            return
        job['observed'] = True
        child = job.get('child')
        self.outcomes.append(dict(index=job.get('index'), adopted=adopted,
            total_seconds=getattr(child, 'elapsed', None),
            body_seconds=getattr(child, 'body_seconds', None),
            peak_rss=getattr(child, 'peak_rss', None), parent_seconds=job.get('handover_seconds')))

    def _claim_ready(self, job, request, budget):
        # owner.condition is held through decoding/validation. Revocation
        # cannot free the storage while this frame owns its large descendants.
        begun = time.perf_counter()
        try:
            dispatch, binding, child = job['dispatch'], job['binding'], job['child']
            raw = dispatch.result(timeout=self.timeout+15, request=request,
                context=self.context,
                child_bytes=self.child_bytes, predicate_units=self.units)
            if not child.exited:
                raise RuntimeError('worker exit not confirmed before adoption')
            self.stats['peak_child_rss'] = max(self.stats['peak_child_rss'], child.peak_rss)
            job['fit'].complete()
            if request.get('schema') == VOLUME_SCHEMA:
                digests = {}  # no separate certificate digest in this family
            elif request['kind'] == 'component-fixed-voxel-face':
                from atlas_tectonics.integration.geometry import moving_face_moments as FM
                digests = {'temporal_integration': FM.source_digest()}
            else:
                from atlas_tectonics.integration.geometry import interface_exclusion as IE
                from atlas_tectonics.integration.geometry import moving_interface_moments as IM
                digests = {'zero_area_certificate': IE.source_digest(), 'moving_interface_moments': IM.source_digest()}
            hint = job['hint']
            if not hint.slot.grow_optional(raw_capacity(len(raw))):
                raise ValueError('actual result-buffer size exceeds optional capacity')
            if not hint.receive_under(self.owner, raw, hashlib.sha256(raw).hexdigest()):
                raise ValueError('optional result slot declined')
            result = hint.claim_measure(self.owner, cls=G.DifferentialMeasure, budget=budget,
                request=request, binding=binding.record(), fit=job['fit'],
                digests=digests)
            if result is None:
                raise ValueError('optional result verification declined')
            self.stats['adopted'] += 1
            self._return_job_leases(job)
            # The hand-over: the parent's seconds to send the request and to adopt its result.
            job['handover_seconds'] = job.get('dispatch_seconds', 0.0)+time.perf_counter()-begun
            self._outcome(job, True)
            return result
        except Exception as error:
            # A decline re-raised from the worker's Future is the exception
            # object that Future keeps. Its traceback now holds this frame
            # and, through it, the caller's, the interface body's and the
            # enclosure's, each with its locals: a cycle that would pin the
            # owner lease and those callers' storage until a cyclic
            # collection, while the serial path they return to needs both.
            error.__traceback__ = None
            self.last_error = str(error)[:4096]
            self.stats['declined'] += 1
        self._outcome(job, False)
        return None

    @staticmethod
    def _return_job_leases(job):
        if job['fit'] is not None:
            job['fit'].release()
            job['fit'] = None
        if job['baseline'] is not None:
            job['baseline'].close()
            job['baseline'] = None

    def _stop(self):
        # ALL children confirmed stopped before ANY child funding is released.
        for job in self.jobs.values():
            job['child'].stop()
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
        while self.jobs:
            key = next(iter(self.jobs))
            job = self.jobs[key]
            job['hint'].close()
            self._return_job_leases(job)
            self.stats['peak_child_rss'] = max(self.stats['peak_child_rss'], job['child'].peak_rss)
            self._outcome(job, False)
            del self.jobs[key]
            job.clear()
        # The caller owns the small session/policy handle. This lease owns the
        # temporary input/receipt/pool graph, which is now gone. Leaving the
        # bulk reservation alive here could itself cause a serial refusal.
        if self.storage is not None:
            self.storage.close()
            self.storage = None

    def close(self):
        if self.closed:
            return
        if self.owner is not None:
            self.owner.__exit__(None, None, None)
            self.owner = None
        if self.directory is not None:
            if self.planner is None:
                self.directory.cleanup()
            else:
                self._remove_directory()
            self.directory = None
        if self.storage is not None:
            self.storage.close()
            self.storage = None
        self.closed = True

    def _remove_directory(self):
        # Planner route only: an explicit session keeps the close() it had.
        # Something outside this process (a scanner, an indexer, a shell
        # sitting in the folder) can hold a temporary file for a moment.
        # Every child is confirmed stopped and its funding returned before
        # this point, so a directory that cannot be removed is a path-free
        # note for the caller's report, never a failed enclosure.
        directory, failure = self.directory, None
        for attempt in range(5):
            try:
                directory.cleanup()
                return
            except Exception as error:
                code = getattr(error, 'winerror', None) or getattr(error, 'errno', None)
                failure = type(error).__name__ if code is None else '%s %s' % (type(error).__name__, code)
            if attempt < 4:
                time.sleep(0.05)
        # cleanup() stops at the first entry it cannot remove and will not run
        # again by itself: take away everything else that can be removed.
        shutil.rmtree(directory.name, ignore_errors=True)
        if os.path.lexists(directory.name):
            self.plan['cleanup'] = failure


class WallParallelSession(InterfaceParallelSession):
    """Same owned workers and stop/adoption guards for rigid fixed-wall flux.

    Jobs are (support, logical_cell_id, axis, {'end': end}). There is no
    moment, endpoint or solved-native-normal variant on this private route.
    Its parent calls the original wall issuer with the mandatory prefix and
    adopts only the complete result bound to that exact eleven-field request.
    """
    _make_request = staticmethod(_wall_request)


class _Served:
    """One batch's child when its worker is kept: the session's per-batch handle.

    run() serves the batch through the worker; served is set once the worker
    has closed the result and created the done file. stop() stops the worker.
    """
    exited = served = False

    def __init__(self, worker, path):
        self.worker, self.path = worker, path
        self.done = threading.Event()
        self.elapsed = self.body_seconds = self.ledger_peak = None
        self.peak_rss, self.stop_seconds = 0, 0.0

    def run(self, binding_bytes):
        worker = self.worker
        try:
            result = worker.serve(self.path, binding_bytes)
            self.served = True
            return result
        finally:
            self.elapsed, self.body_seconds, self.peak_rss = worker.elapsed, worker.body_seconds, worker.peak_rss
            self.ledger_peak = worker.ledger_peak

    def stop(self):
        begun = time.perf_counter()
        try:
            self.worker.stop()
        finally:
            self.stop_seconds += time.perf_counter()-begun


class BatchParallelSession(InterfaceParallelSession):
    """Rolling one-shot workers, each answering one bounded batch of exact requests.

    The scheduler that owns this session decides which upcoming requests form
    a batch and when; nothing here estimates or selects. launch() funds one
    worker envelope and baseline for the whole batch and starts it. claim()
    adopts one member at the parent's serial position, after its worker has
    exited and the batch completion was verified against the live request
    list, sources and runtime; the member is then funded and validated as a
    one-job result is. A member the worker did not answer runs the parent's
    unchanged serial body, as every request outside a batch does.

    A worker that fails, a completion that does not verify, a declined
    adoption and a launch that fails after its funding began each revoke the
    whole session: every child is confirmed stopped, then every optional
    admission returns, and nothing further is launched or adopted. retire()
    stops and returns one batch that the parent has passed. ended() names
    which of these it was, or a revocation from outside.

    The session owns its registration before entry can be interrupted. An
    interruption during a child stop still attempts every sibling stop and
    keeps all batch funding; only an explicit close may resume that cleanup.
    A real unconfirmed shutdown remains failed and charged. These safeguards
    do not make the lower-level funding operations interruption-atomic.
    """
    def __init__(self, *, budget, max_width_m3, max_leaves, wall, workers=2, child_bytes=128 << 20,
                 predicate_units=1 << 34, timeout_seconds=1800, budget_fraction=1.0, keep_workers=False,
                 batch_seconds=None):
        if type(keep_workers) is not bool:
            raise ValueError('keep_workers must be a boolean')
        if (type(workers) is not int or workers < 1 or type(wall) is not bool
                or type(budget_fraction) not in (int, float) or not 0 < budget_fraction <= 1):
            raise ValueError('a positive worker count, an explicit request kind and a fraction in (0, 1] required')
        super().__init__(budget=budget, context=None, max_width_m3=max_width_m3, max_leaves=max_leaves,
                         child_bytes=child_bytes, predicate_units=predicate_units,
                         timeout_seconds=timeout_seconds)
        self.wall, self.workers, self.fraction = wall, workers, budget_fraction
        self._width_text = G._qtext(G.W._q(max_width_m3))
        self.batches, self.members, self._facts = [], {}, {}
        # Only the rolling interface owner supplies this private execution limit.
        self.batch_seconds, self.handbacks, self.returned = batch_seconds, deque(), set()
        self.log = deque(maxlen=BATCH_LOG)
        self.on_wait = None
        self.cause = None       # why the session revoked itself, if it did
        self.stats.update(jobs=0, results=0, decided=0, refused=0, retired=0, peak_child_ledger=0)
        if batch_seconds is not None:
            self.stats['returned'] = 0
        # Parent seconds spent on the optional route, for the scheduler's own accounting.
        self.seconds = dict(launch=0.0, receive=0.0, adopt=0.0, waited=0.0)
        # Kept workers: each holds its own baseline for its life; off is the one-shot path.
        self.keep, self.kept, self._homes = keep_workers, [], 0
        if keep_workers:
            self.stats['recycled'] = 0

    def prepare(self, jobs):
        raise RuntimeError('a batch session is opened and launched by its scheduler')

    def _support_facts(self, support):
        """(support id, interval id, start, end, shippable) of one issued support, decoded once."""
        if type(support) is CompactSupport or getattr(support, '_compact_ref', None) is not None:
            return batch_facts(self, support, transport)
        held = self._facts.get(id(support))
        if held is None or held[0] is not support:
            if len(self._facts) >= 512:
                self._facts.clear()
            record = support.record()
            held = self._facts[id(support)] = (support, (support.support_id, record['interval_id'],
                record['start_time_s'], record['end_time_s'], transport(support) is not None))
        return held[1]

    def shippable(self, support, other=None):
        """Whether these supports fit the optional transport; never an error."""
        return self._support_facts(support)[4] and (other is None or self._support_facts(other)[4])

    def member_request(self, support, key, name, pair):
        """The request the issuer itself builds for this job."""
        identity, interval, start, end, _ = self._support_facts(support)
        if self.wall:
            if pair.keys() != {'end'}:
                raise ValueError('a wall job requires exactly its end selector')
            return dict(schema=G.MEASURE_SCHEMA, kind=WALL_KIND, support_id=identity, interval_id=interval,
                logical_cell_id=key, axis=name, end=pair['end'], start_time_s=start, end_time_s=end,
                max_width_m3=self._width_text, max_leaves=self.leaves)
        other = pair.get('other_support')
        return dict(schema=G.MEASURE_SCHEMA, kind='component-moving-radial-interface',
            support_id=identity, interval_id=interval, logical_cell_id=key, constraint_name=name,
            other_support_id=None if other is None else self._support_facts(other)[0],
            other_logical_cell_id=pair.get('other_logical_cell_id'),
            start_time_s=start, end_time_s=end, max_width_m3=self._width_text, max_leaves=self.leaves)

    def open(self, context):
        """Parent storage, the strict context, the owner and the directory, in the other routes' order.

        context() is called only after the storage lease. False means nothing
        is held and the session is closed; plan['funding'] says what refused.
        An interrupt in here closes the session before it goes on: the caller
        may not know this session yet.
        """
        if self.prepared or self.closed:
            raise RuntimeError('one open per batch session')
        self.prepared = True
        try:
            self.storage = SlotLease.attempt(R, self.budget, PARENT_STORAGE)
            if self.storage is None:
                self.plan['funding'] = 'parent storage refused'
            else:
                self.context = context()
                if self._open_owner() is not None:
                    return True
                self.plan['funding'] = 'owner lease refused' if self.closed else 'owner revoked'
        except Exception as error:
            self.last_error = str(error)[:4096]
        except BaseException:
            self.close()
            raise
        # As for the other routes: a failed shutdown is never suppressed.
        self.close()
        return False

    def running(self):
        return sum(not batch['child'].done.is_set() for batch in self.batches)

    def done(self, batch):
        """Scheduling hint: has this batch's worker returned, well or badly?"""
        return batch['child'].done.is_set()

    def busy(self):
        """Scheduling hint: is a batch worker still running?"""
        return any(not batch['child'].done.is_set() for batch in self.batches)

    def active(self):
        return self.owner is not None and not self.closed and self.owner.state == 'ACTIVE'

    def ended(self):
        """(reason, detail) for a session that is no longer active: its own failure, or a revocation."""
        return self.cause or 'session revoked', self.last_error

    def check(self):
        """Whether the session is active and no finished worker has failed; a failure revokes it now.

        Without this a failed worker would be noticed only when the parent
        reaches one of its members, and further batches could be started
        meanwhile. Nothing is consumed: the completion of a worker that
        finished well is still verified at its first claim.
        """
        owner = self.owner
        if not self.active():
            return False
        failed = False
        with owner.condition:
            for batch in self.batches:
                if batch['failed']:
                    failed = True
                    break
                if batch['answers'] is not None:
                    continue
                future = batch['dispatch']._future
                if future is not None and future.done():
                    error = future.exception()
                    if error is not None:
                        # As _claim_ready: the Future's exception must not pin frames.
                        error.__traceback__ = None
                        self.last_error = str(error)[:4096]
                        batch['failed'] = failed = True
                    elif self.batch_seconds is not None:
                        # A completed hand-back frees its worker before any fresh selection.
                        self._receive(batch)
                        failed = failed or batch['failed']
                    if failed:
                        break
        if failed:
            self.cause = self.cause or 'worker failure'
            owner.revoke()
        return self.active()

    def take_handbacks(self):
        """Verified cuts for the scheduler, consumed on the parent thread outside the owner lock."""
        cuts = list(self.handbacks)
        self.handbacks.clear()
        return cuts

    def launch(self, jobs, timeout):
        """Fund and start one worker for (support, key, name, pair) jobs; the batch, or None.

        None starts nothing: no free worker, an inactive owner, a refused
        envelope or baseline (counted in stats['refused']), or jobs that
        cannot be shipped or repeat a live request (last_error says which).
        A failure after funding began revokes the session.
        """
        owner = self.owner
        if owner is None or self.closed or not jobs:
            return None
        begun = time.perf_counter()
        try:
            with owner.condition:
                if owner.state != 'ACTIVE' or self.running() >= self.workers:
                    return None
                try:
                    requests, tokens, inputs = self._bind_jobs(jobs)
                except ValueError as error:
                    # Nothing is held yet: these jobs simply stay with the parent.
                    self.last_error = str(error)[:4096]
                    return None
                return self._start(requests, tokens, inputs, timeout)
        except Exception as error:
            error.__traceback__ = None
            self.last_error = str(error)[:4096]
        finally:
            self.seconds['launch'] += time.perf_counter()-begun
        self.cause = self.cause or 'launch failure'
        owner.revoke()
        return None

    def _bind_jobs(self, jobs):
        requests, inputs, size = [], InputMap(MAX_INPUT, PARENT_STORAGE), 0
        for support, key, name, pair in jobs:
            other = pair.get('other_support')
            if not self.shippable(support, other):
                raise ValueError('a batch support exceeds the optional transport envelope')
            requests.append(self.member_request(support, key, name, pair))
            for item in (support, other):
                if item is None:
                    continue
                identity = self._support_facts(item)[0]
                if identity in inputs:
                    continue
                if type(item) is CompactSupport and size+item.encoded_size > MAX_BATCH_INPUT:
                    # Refused before its exact copy is made or charged.
                    raise ValueError('batch exceeds the optional transport envelope')
                inputs.add(identity, item)
                size += len(inputs[identity])
        if size > MAX_BATCH_INPUT or not 1 <= len(requests) <= BATCH_LIMIT:
            raise ValueError('batch exceeds the optional transport envelope')
        tokens = [canonical(request) for request in requests]
        if len(set(tokens)) != len(tokens) or any(token in self.members for token in tokens):
            raise ValueError('duplicate optional request')
        return requests, tokens, inputs

    def _start(self, requests, tokens, inputs, timeout):
        begun = time.perf_counter()
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('finite positive batch timeout required')
        timeout = min(self.timeout, timeout)    # never beyond the ceiling this session was built with
        worker = None
        if self.keep:
            if self.batch_seconds is not None:
                for idle in tuple(self.kept):
                    if idle.batch is None and idle.process is not None and idle.process.poll() is not None:
                        # A redirector's exit alone proves nothing about its worker tree.
                        with idle.lock:
                            idle._surveyed = None
                            live, whole = idle._measure(idle.process)
                            dead = whole and not live and idle._worker_known()
                        if dead:
                            self.stats['recycled'] += 1
                            self._end_worker(idle)
            # One baseline for each live kept worker, one envelope for each batch.
            worker = next((kept for kept in self.kept if kept.batch is None), None)
            if worker is None and len(self.kept) >= self.workers:
                return None
            held = PARENT_STORAGE+self.child_bytes*len(self.batches)+CHILD_BASELINE*len(self.kept)
            need = self.child_bytes+(0 if worker is not None else CHILD_BASELINE)
        else:
            # Everything this session holds, with one more worker, stays inside its share of what
            # the budget would have available without it. A finished worker has returned its baseline.
            held = PARENT_STORAGE+sum(self.child_bytes+(0 if batch['answers'] is not None else CHILD_BASELINE)
                                      for batch in self.batches)
            need = self.child_bytes+CHILD_BASELINE
        if held+need > self.fraction*(self.budget.available_bytes+held):
            self.stats['refused'] += 1
            return None
        fit = FitWitness.attempt(R, self.budget, self.child_bytes, self.units)
        if fit is None:
            self.stats['refused'] += 1
            return None
        baseline = batch = None
        try:
            if worker is None:
                baseline = SlotLease.attempt(R, self.budget, CHILD_BASELINE)
                if baseline is None:
                    fit.release()
                    self.stats['refused'] += 1
                    return None
            # Only this concrete producer establishes the fixed moving-interface shape.
            # Volume/initial/pressure subclasses and walls retain the raw validating factory.
            factory = (BatchBinding._create_owned if type(self) is BatchParallelSession and
                       not self.wall and self.batch_seconds is not None else BatchBinding.create)
            binding = factory(requests=requests,
                context=self.context, child_bytes=self.child_bytes, predicate_units=self.units,
                batch_seconds=self.batch_seconds)
            path = Path(self.directory.name)/('batch-%d' % self.stats['started'])
            (path/'inputs').mkdir(parents=True)
            # The batch's own encoded inputs; each child still verifies every digest.
            for identity, raw in inputs.items():
                with (path/'inputs'/(identity+'.json')).open('xb') as stream:
                    stream.write(raw)
            with (path/'binding.json').open('xb') as stream:
                stream.write(binding.encoded)
            if not self.keep:
                child = _Child(path, timeout, CHILD_BASELINE+self.child_bytes, interval=SURVEY)
            else:
                if worker is None:
                    home = Path(self.directory.name)/('worker-%d' % self._homes)
                    home.mkdir()
                    with (home/'kept').open('xb'):
                        pass
                    worker = _Child(home, timeout, CHILD_BASELINE+self.child_bytes, interval=SURVEY, kept=True)
                    # From here the worker owns the baseline; _stop closes it after its stop is confirmed.
                    worker.baseline, baseline = baseline, None
                    self._homes += 1
                    self.kept.append(worker)
                worker.deadline = timeout
                child = _Served(worker, path)
            batch = dict(index=self.stats['started'], fit=fit, baseline=baseline, child=child,
                dispatch=OwnedBatchDispatch(binding), inputs=inputs, requests=requests, tokens=tokens,
                binding=binding, digest=hashlib.sha256(binding.encoded).hexdigest(), path=str(path),
                timeout=timeout, answers=None, left=len(requests), failed=False, results=0, decided=0,
                adopted=0, declined=0, clock=[0.0])
            if self.pool is None:
                self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='atlas-batch')
            # From here the stop path owns the batch: it confirms the child before any release.
            if worker is not None:
                worker.batch = batch
            self.batches.append(batch)
            for index, token in enumerate(tokens):
                self.members[token] = batch, index
            batch['dispatch'].submit(self.pool, child.run)
            batch['dispatch']._future.add_done_callback(lambda _future, event=child.done: event.set())
        except BaseException:
            if batch is None or not any(held is batch for held in self.batches):
                fit.release()
                if baseline is not None:
                    baseline.close()
            raise
        self.stats['started'] += 1
        self.stats['jobs'] += len(requests)
        batch['start_seconds'] = time.perf_counter()-begun    # Part B parent mark
        return batch

    def claim(self, request, budget):
        if self.owner is None or self.closed or budget is not self.budget:
            return None
        key = canonical(request)
        owner = self.owner
        result, failed, clock = None, False, None
        while True:
            retry = False
            with owner.condition:
                if owner.state != 'ACTIVE':
                    return None
                member = self.members.get(key)
                if member is None:
                    if key not in self.returned:
                        return None
                    retry, event = True, None
                else:
                    batch, index = member
                    future = batch['dispatch']._future
                    if batch['failed'] or future is None or future.done():
                        if self.batch_seconds is None:
                            # Preserve the shared disabled route: the current decided member
                            # belongs to _member, not _receive's discount of other decisions.
                            del self.members[key]
                            result, failed = self._member(batch, index, request, budget)
                        else:
                            if batch['answers'] is None and not batch['failed']:
                                self._receive(batch)
                            if batch['failed']:
                                result, failed = self._member(batch, index, request, budget)
                            elif key in self.members:
                                del self.members[key]
                                result, failed = self._member(batch, index, request, budget)
                                self.returned.discard(key)
                            else:
                                retry = key in self.returned
                        event = None
                    else:
                        # Waiting retains only the small event and counter, not the batch graph
                        # that a revocation may free meanwhile.
                        event, clock = batch['child'].done, batch['clock']
                batch = future = member = None
            if failed:
                # Failed custody wins over any returned marker from an earlier dispatch.
                owner.revoke()
                return result
            if retry:
                # Enabled sessions belong to the rolling scheduler. It gives this pinned
                # serial head the freed prefix slot, or uses existing whole-session recovery.
                self.on_wait()
                continue
            if event is None:
                return result
            begun = time.perf_counter()
            event.wait(1)
            self.waits += 1
            waited = time.perf_counter()-begun
            clock[0] += waited
            self.seconds['waited'] += waited
            self._heartbeat()
            if self.on_wait is not None:
                # The scheduler may start further batches while this thread only waits.
                self.on_wait()

    def _member(self, batch, index, request, budget):
        """One member at its serial position: (funded measure or None, whether to revoke)."""
        if batch['answers'] is None and not batch['failed']:
            self._receive(batch)
        if batch['failed']:
            self.stats['declined'] += 1
            batch['declined'] += 1
            return None, True
        answer, batch['answers'][index] = batch['answers'][index], None
        batch['left'] -= 1
        result, failed = None, False
        if type(answer) is bytes:
            if type(self) is BatchParallelSession and not self.wall and self.batch_seconds is not None:
                try:
                    result = self._adopt(batch, index, request, budget, answer, receipt_request=batch['tokens'][index])
                finally:
                    batch['requests'][index] = None
            else:
                result = self._adopt(batch, index, request, budget, answer)
            failed = result is None
        elif answer == 'declined':
            self.stats['declined'] += 1
            batch['declined'] += 1
        if not batch['left'] and not failed:
            self._finish(batch)
        return result, failed

    def _receive(self, batch):
        # owner.condition is held through decoding and validation, as for one job.
        begun = time.perf_counter()
        interface = type(self) is BatchParallelSession and not self.wall and self.batch_seconds is not None
        try:
            child = batch['child']
            dispatch = batch['dispatch']
            receiver = dispatch._interface_result if interface else dispatch.result
            args = (batch['tokens'], batch['digest']) if interface else ()
            answers = receiver(*args, timeout=batch['timeout']+15, requests=batch['requests'],
                context=self.context,
                child_bytes=self.child_bytes, predicate_units=self.units, batch_seconds=self.batch_seconds)
            if not (child.exited or child.served):
                raise RuntimeError('worker exit not confirmed before adoption')
            if self.keep:
                # Stop/recycle must succeed before accepting answers or exposing a suffix.
                self._release(child.worker)
            self.stats['peak_child_rss'] = max(self.stats['peak_child_rss'], child.peak_rss)
            batch['fit'].complete()
            # The child process is gone, or a kept worker has finished with this batch and keeps
            # its own baseline. The envelope stays charged until the last adoption.
            if batch['baseline'] is not None:
                batch['baseline'].close()
            cut = None
            for index, answer in enumerate(answers):
                if type(answer) is tuple:
                    # Only the owned interface receiver can return a staged proof.
                    batch['requests'][index] = answer
                    answer = answers[index] = answer[0]
                if type(answer) is bytes:
                    batch['results'] += 1
                elif answer == 'decided':
                    batch['decided'] += 1
                    if self.members.get(batch['tokens'][index], (None,))[0] is batch:
                        # The parent's own exact prefix issues this member and never claims it.
                        # The member being claimed right now is counted off by its claim instead.
                        del self.members[batch['tokens'][index]]
                        batch['left'] -= 1
                elif answer == 'returned':
                    if cut is None:
                        cut = index
                    token = batch['tokens'][index]
                    if self.members.get(token, (None,))[0] is batch:
                        del self.members[token]
                        batch['left'] -= 1
                        self.returned.add(token)
            if cut is not None:
                batch['returned'] = len(answers)-cut
                self.stats['returned'] += batch['returned']
            snapshot = batch.pop('schedule', None)
            if cut is not None:
                held, rows = snapshot
                self.handbacks.append((held, rows[cut-1][1], rows[cut:]))
            self.stats['results'] += batch['results']
            self.stats['decided'] += batch['decided']
            if interface:
                dispatch._consumed = batch['requests']
            batch['answers'] = answers
            # result() consumed this Future once. Its raw receipt need not outlive acceptance.
            batch['dispatch']._future = None
        except Exception as error:
            # As _claim_ready: the Future's exception must not pin these frames.
            error.__traceback__ = None
            self.last_error = str(error)[:4096]
            batch['failed'] = True
            if interface:
                batch['requests'] = None
            self.cause = self.cause or 'worker failure'
        finally:
            batch['receive_seconds'] = time.perf_counter()-begun    # Part B parent mark
            self.seconds['receive'] += batch['receive_seconds']

    def _adopt(self, batch, index, request, budget, answer, *, receipt_request=None):
        begun = time.perf_counter()
        hint = None
        try:
            if request.get('schema') == VOLUME_SCHEMA:
                digests = {}  # no separate certificate digest in this family
            elif request['kind'] == WALL_KIND:
                from atlas_tectonics.integration.geometry import moving_face_moments as FM
                digests = {'temporal_integration': FM.source_digest()}
            else:
                from atlas_tectonics.integration.geometry import interface_exclusion as IE
                from atlas_tectonics.integration.geometry import moving_interface_moments as IM
                digests = {'zero_area_certificate': IE.source_digest(), 'moving_interface_moments': IM.source_digest()}
            member = dict(schema='private.parallel-batch-member.v1', batch=batch['digest'], index=index)
            # Funded at its own serial position, then exactly the one-job receive and claim.
            slot = SlotLease.attempt(R, self.budget, raw_capacity(len(answer)))
            if slot is None:
                raise ValueError('optional result slot refused')
            try:
                hint = MeasureHint(slot, max_payload=MAX_RESULT, request=request, binding=member, fit=batch['fit'])
            except BaseException:
                slot.close()
                raise
            dispatch = batch['dispatch'] if receipt_request is not None else None
            # The hint checks this candidate digest against actual dispatch custody
            # under the live fit. An independently supplied payload uses its own hash.
            entry = batch['requests'][index] if type(dispatch) is OwnedBatchDispatch else None
            digest = entry[2] if entry is not None else hashlib.sha256(answer).hexdigest()
            if not hint.receive_under(self.owner, answer, digest):
                raise ValueError('optional result slot declined')
            if receipt_request is None:
                result = hint.claim_measure(self.owner, cls=G.DifferentialMeasure, budget=budget,
                    request=request, binding=member, fit=batch['fit'], digests=digests)
            else:
                result = hint._claim_measure(self.owner, cls=G.DifferentialMeasure, budget=budget,
                    request=request, binding=member, fit=batch['fit'], digests=digests,
                    receipt_request=receipt_request, receipt_dispatch=dispatch)
            if result is None:
                raise ValueError('optional result verification declined')
            self.stats['adopted'] += 1
            batch['adopted'] += 1
            return result
        except Exception as error:
            error.__traceback__ = None
            self.last_error = str(error)[:4096]
            self.cause = self.cause or 'adoption declined'
            self.stats['declined'] += 1
            batch['declined'] += 1
            return None
        finally:
            if hint is not None:
                hint.close()    # returns the slot unless the measure took it over
            self.seconds['adopt'] += time.perf_counter()-begun

    def _finish(self, batch):
        """Return everything a batch still holds; its child is already confirmed stopped.

        The envelope and baseline go back before the batch is forgotten, so an
        interrupt in between leaves it to the close that follows. Both returns
        may be repeated.
        """
        dispatch = batch['dispatch']
        if type(dispatch) is OwnedBatchDispatch and dispatch._consumed is batch['requests']:
            dispatch._consumed = True
            batch['requests'] = None
        batch['fit'].release()
        if batch['baseline'] is not None:    # never a kept worker's baseline
            batch['baseline'].close()
        self.batches = [held for held in self.batches if held is not batch]
        for token in batch['tokens']:
            if self.members.get(token, (None,))[0] is batch:
                del self.members[token]
        child = batch['child']
        self.stats['peak_child_rss'] = max(self.stats['peak_child_rss'], child.peak_rss)
        self.stats['peak_child_ledger'] = max(self.stats['peak_child_ledger'], child.ledger_peak or 0)
        self.stats['retired'] += 1
        self.log.append(dict(index=batch['index'], jobs=len(batch['tokens']), results=batch['results'],
            decided=batch['decided'], adopted=batch['adopted'], declined=batch['declined'],
            failed=batch['failed'], total_seconds=child.elapsed, body_seconds=child.body_seconds,
            peak_rss=child.peak_rss, ledger_peak=child.ledger_peak, waited_seconds=batch['clock'][0],
            start_seconds=batch.get('start_seconds'),
            receive_seconds=batch.get('receive_seconds'), stop_seconds=child.stop_seconds,
            **({'returned': batch['returned']} if 'returned' in batch else {})))
        # A queued cut already owns its one-way suffix snapshot. An unreceived batch
        # instead discards its still-owned snapshot only after confirmed termination.
        batch.pop('schedule', None)
        worker = getattr(child, 'worker', None)
        if worker is not None and worker.batch is batch:
            worker.batch = None
        if dispatch is not None:
            dispatch._future = None
        batch['dispatch'] = batch['binding'] = None
        batch['answers'] = batch['inputs'] = batch['requests'] = batch['tokens'] = None
        shutil.rmtree(batch['path'], ignore_errors=True)

    def retire(self, batch):
        """Stop and return one batch the parent has passed; an unconfirmed stop propagates."""
        owner = self.owner
        if owner is None or self.closed:
            return
        failed = False
        with owner.condition:
            if owner.state == 'ACTIVE' and any(held is batch for held in self.batches):
                if batch['failed']:
                    failed = True
                else:
                    if not self.keep:
                        batch['child'].stop()
                    elif batch['answers'] is None:
                        # Its worker is still on it: stopped, as a one-shot worker is.
                        batch['child'].stop()
                        self._end_worker(batch['child'].worker)
                    self._finish(batch)
        if failed:
            owner.revoke()

    def _release(self, worker):
        """After a received batch: the worker is idle again, or ended above its baseline (design 4.4).

        A worker being recycled keeps its batch and its place in kept until its stop is confirmed (V-4):
        if stop() raises, no batch is handed to it and _stop tries it again.
        """
        if worker.rss is None or worker.rss > CHILD_BASELINE:
            self.stats['recycled'] += 1
            self._end_worker(worker)
        else:
            worker.batch = None

    def _end_worker(self, worker):
        batch = worker.batch
        worker.stop()
        if worker.batch is batch:
            worker.batch = None
        # Its stop is confirmed: only now is its baseline returned.
        self.kept = [kept for kept in self.kept if kept is not worker]
        worker.baseline.close()
        self._ended(worker)

    def _ended(self, worker):
        if worker.bad_end is not None:
            self.cause = self.cause or 'worker failure'
            self.last_error = worker.bad_end[:4096]

    def _stop(self):
        # ALL children confirmed stopped before ANY child funding is released. One that
        # cannot be confirmed must not leave the others unsignalled: each stop
        # is attempted, then shutdown failure or cancellation propagates without release.
        unconfirmed = interrupted = None
        for child in [batch['child'] for batch in self.batches]+self.kept:
            try:
                child.stop()
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    interrupted = interrupted or error
                else:
                    unconfirmed = unconfirmed or error
        if unconfirmed is not None:
            # A real shutdown failure stays failed, even when another child
            # was interrupted. Never turn uncertainty into retry authority.
            if interrupted is not None:
                raise unconfirmed from interrupted
            raise unconfirmed
        if interrupted is not None:
            # Every sibling has been signalled, but no funding is returned.
            # The owner permits only an explicit close to resume this cleanup.
            raise interrupted
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
        for batch in tuple(self.batches):
            self._finish(batch)
        for worker in self.kept:
            worker.baseline.close()
            self._ended(worker)
        self.kept = []
        self.members.clear()
        self.returned.clear()
        self.handbacks.clear()
        if self.storage is not None:
            self.storage.close()
            self.storage = None

    def close(self):
        if self.closed:
            return
        if self.owner is not None:
            self.owner.__exit__(None, None, None)
            self.owner = None
        if self.directory is not None:
            self._remove_directory()
            self.directory = None
        if self.storage is not None:
            self.storage.close()
            self.storage = None
        # The decode cache names issued supports: a closed session keeps none alive.
        self._facts.clear()
        self.on_wait = None
        self.closed = True

from atlas_tectonics._private.integration.geometry.partition_routing_patch import (CompactSupport, compact_transport, support_header,
    as_native, batch_facts, InputMap)
