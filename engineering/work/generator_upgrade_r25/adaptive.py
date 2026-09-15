"""Invocation-local cost selection; no duplicate probes or historical timings.

Only identical producer/context/input/dependency payloads share observations.
Different regional inputs normally remain serial. Startup and IPC allowances are
engineering estimates, not guaranteed execution costs or scientific claims.
"""
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import math
import os
import threading
import time

from work.generator_upgrade_r21 import _snapshot_contract as snapshot
from work.generator_runtime_r12.parallel import _record

PROFILE_LIMIT = 128
IPC_BYTES_PER_SECOND = 16 * 1024 * 1024
SAFETY_FACTOR = 1.25


class AdaptiveBackend:
    def __init__(self, local_worker, pool, *, startup_budget_s=1.5, clock=time.perf_counter):
        if not callable(local_worker) or not callable(clock):
            raise ValueError('callable local worker and clock required')
        if (type(startup_budget_s) not in (int, float)
                or not math.isfinite(startup_budget_s) or startup_budget_s < 0):
            raise ValueError('finite nonnegative startup budget required')
        capacity = getattr(pool, 'capacity', None)
        if type(capacity) is not int or capacity not in (1, 2):
            raise ValueError('adaptive candidate capacity must be one or two')
        if any(not callable(getattr(pool, name, None))
               for name in ('__enter__', 'submit', 'receive', 'close')):
            raise ValueError('explicit candidate submit/receive pool required')
        self._local_worker, self._pool, self._clock = local_worker, pool, clock
        self._capacity, self._budget = capacity, float(startup_budget_s)
        self._queue, self._pending, self._seen = deque(), {}, set()
        self._profiles, self._local_ids, self._jobs = {}, [], []
        self._promoted, self._state = False, 'OPEN'
        self._reason, self._decision = 'NO_OBSERVATIONS', 'SERIAL'
        self._saving, self._threshold, self._peak = 0.0, 0.0, 0
        self._lock = threading.Lock()

    @property
    def capacity(self):
        return self._capacity

    @property
    def promoted(self):
        return self._promoted

    @property
    def effective_workers(self):
        return self._capacity if self._promoted else 1

    @property
    def observed_pids(self):
        return tuple(self._pool.observed_pids) if self._promoted else ()

    @property
    def selection(self):
        return {'decision': self._decision, 'reason': self._reason,
                'promoted': self._promoted, 'startup_budget_s': self._budget,
                'ipc_bytes_per_second': IPC_BYTES_PER_SECOND, 'safety_factor': SAFETY_FACTOR,
                'predicted_saving_s': self._saving, 'required_saving_s': self._threshold,
                'local_executed_stage_ids': list(self._local_ids),
                'profile_count': len(self._profiles), 'profile_limit': PROFILE_LIMIT,
                'profile_scope': 'EXACT_INPUTS_THIS_INVOCATION_ONLY',
                'different_inputs_cost_equivalence_claimed': False}

    @property
    def timings(self):
        return {'local_jobs': deepcopy(self._jobs), 'peak_pending': self._peak,
                'parallel': deepcopy(self._pool.timings) if self._promoted else {}}

    def _fail(self, primary):
        self._state = 'FAILED'
        self._queue.clear()
        self._pending.clear()
        try:
            self._pool.close()
        except BaseException as cleanup:
            primary.adaptive_cleanup_errors = [type(cleanup).__name__ + ': ' + str(cleanup)]

    @contextmanager
    def _exclusive(self):
        if self._state != 'OPEN' or not self._lock.acquire(blocking=False):
            raise RuntimeError('open exclusively used adaptive backend required')
        try:
            yield
        except BaseException as exc:
            self._fail(exc)
            raise
        finally:
            self._lock.release()

    def _prepare(self, jobs):
        if type(jobs) is not list:
            raise ValueError('explicit job list required')
        entries, seen = [], set()
        for job in jobs:
            snapshot.exact(job, ('stage_id', 'producer_id', 'context', 'inputs', 'incoming'),
                           'adaptive job')
            ident, producer = job['stage_id'], job['producer_id']
            if any(type(value) is not str or not value or len(value) > 256
                   or value.strip() != value for value in (ident, producer)):
                raise ValueError('bounded nonblank stage and producer identities required')
            if ident in seen or ident in self._seen:
                raise ValueError('unique adaptive stage identity required')
            if any(type(job[key]) is not dict for key in ('context', 'inputs', 'incoming')):
                raise ValueError('explicit context/input/dependency mappings required')
            payload_bytes = len(snapshot.encoded(job))
            key = hashlib.sha256(snapshot.encoded({name: value for name, value in job.items()
                                                  if name != 'stage_id'})).hexdigest()
            entries.append((ident, deepcopy(job), key, payload_bytes))
            seen.add(ident)
        return entries

    def _submit(self, entries):
        if len(entries) + len(self._pending) > self._capacity:
            raise ValueError('adaptive submission exceeds candidate capacity')
        for entry in entries:
            self._pending[entry[0]] = entry
            self._seen.add(entry[0])
            self._queue.append(entry)
        self._peak = max(self._peak, len(self._pending))
        if self._promoted and entries:
            self._pool.submit([entry[1] for entry in self._queue])
            self._queue.clear()

    def submit(self, jobs):
        with self._exclusive():
            if type(jobs) is not list or len(jobs) + len(self._pending) > self._capacity:
                raise ValueError('adaptive submission exceeds candidate capacity')
            self._submit(self._prepare(jobs))

    def _should_promote(self):
        self._saving, self._threshold = 0.0, 0.0
        if self._capacity < 2:
            self._reason = 'CANDIDATE_CAPACITY_ONE'
        elif len(self._queue) < 2:
            self._reason = 'FEWER_THAN_TWO_READY_JOBS'
        elif any(self._profiles.get(entry[2], {}).get('count', 0) < 2 for entry in self._queue):
            self._reason = 'FEWER_THAN_TWO_COMPARABLE_SAMPLES'
        else:
            costs = [self._profiles[entry[2]]['minimum_s'] for entry in self._queue]
            self._saving = sum(costs) - max(costs)
            self._threshold = SAFETY_FACTOR * (self._budget
                + sum(entry[3] for entry in self._queue) / IPC_BYTES_PER_SECOND)
            if self._saving > self._threshold:
                self._decision, self._reason = 'PARALLEL', 'OBSERVED_SAVING_EXCEEDS_BUDGET'
                return True
            self._reason = 'OBSERVED_SAVING_DOES_NOT_EXCEED_BUDGET'
        return False

    def _receive(self):
        if not self._pending:
            raise ValueError('no pending adaptive jobs')
        if not self._promoted and self._should_promote():
            self._pool.__enter__()
            self._promoted = True
            self._pool.submit([entry[1] for entry in self._queue])
            self._queue.clear()
        if self._promoted:
            result = self._pool.receive()
            if (type(result) is not dict or not result
                    or not set(result) <= self._pending.keys()):
                raise ValueError('exact nonempty adaptive completion inventory required')
            for value in result.values():
                _record(value)
            for ident in result:
                del self._pending[ident]
            return result
        ident, job, key, _ = self._queue.popleft()
        self._local_ids.append(ident)
        started = self._clock()
        result = self._local_worker(job)
        elapsed = self._clock() - started
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('finite nonnegative observed duration required')
        _record(result)
        self._jobs.append({'stage_id': ident, 'pid': os.getpid(), 'wall_s': elapsed})
        profile = self._profiles.get(key)
        if profile is not None:
            profile['count'] += 1
            profile['minimum_s'] = min(profile['minimum_s'], elapsed)
        elif len(self._profiles) < PROFILE_LIMIT:
            self._profiles[key] = {'count': 1, 'minimum_s': elapsed}
        del self._pending[ident]
        return {ident: result}

    def receive(self):
        with self._exclusive():
            return self._receive()

    def execute(self, jobs):
        with self._exclusive():
            if self._pending:
                raise RuntimeError('cannot mix wave execution with pending adaptive jobs')
            entries = self._prepare(jobs)  # Reject the whole inventory before any work.
            order = [entry[0] for entry in entries]
            next_index, result = 0, {}
            while next_index < len(entries) or self._pending:
                count = min(self._capacity - len(self._pending), len(entries) - next_index)
                if count:
                    self._submit(entries[next_index:next_index + count])
                    next_index += count
                result.update(self._receive())
            return {ident: result[ident] for ident in order}

    def close(self):
        self._queue.clear()
        self._pending.clear()
        if self._state != 'FAILED':
            self._state = 'CLOSED'
        self._pool.close()
