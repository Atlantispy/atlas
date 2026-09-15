"""Source-bound R24 workers and incremental use of the existing spawn pool."""
from concurrent.futures import FIRST_COMPLETED, wait
import time
from work.generator_runtime_r12 import parallel as native

_REGISTRY = None


def worker_init(specifications, cache, cache_root):
    global _REGISTRY
    from . import registry
    built = {}
    for operation, spec in specifications.items():
        registered = registry.registration(operation, spec['port'], cache=cache,
                                             cache_root=cache_root)
        if registered['sha256'] != spec['sha256']:
            raise ValueError('worker producer/source identity differs')
        built[operation] = registered
    _REGISTRY = built


def worker_run(job):
    from work.generator_upgrade_r21 import _snapshot_contract as snapshot
    snapshot.exact(job, ('stage_id','producer_id','context','inputs','incoming'), 'R24 worker job')
    if _REGISTRY is None or job['producer_id'] not in _REGISTRY:
        raise ValueError('uninitialised or unregistered R24 worker')
    registered = _REGISTRY[job['producer_id']]
    registered['verify']()
    result = registered['run'](job['context'], job['inputs'], job['incoming'])
    registered['verify']()
    return {'product': result, 'artifacts': {}, 'diagnostics': {}}


class PoolBackend(native.PoolBackend):
    """The same bounded spawn pool, exposing only completed validated records.

Streaming consumers perform scientific validation before dependency release.
Pending children are cancelled and running workers joined on any failure/exit.
"""
    def __init__(self, worker, **options):
        super().__init__(worker, **options)
        self._pending = {}
        self._seen = set()

    @property
    def capacity(self):
        return self.effective_workers

    def _fail(self):
        self._state = 'FAILED'
        for future in self._pending:
            future.cancel()
        self._pending.clear()
        super().close()

    def submit(self, jobs):
        if self._state != 'OPEN' or not self._lock.acquire(blocking=False):
            raise RuntimeError('submission requires an open, exclusively used backend')
        try:
            if type(jobs) is not list or len(jobs)+len(self._pending) > self.capacity:
                raise ValueError('submission exceeds bounded worker capacity')
            seen = set()
            for job in jobs:
                ident = job.get('stage_id') if type(job) is dict else None
                if (type(ident) is not str or not ident or len(ident) > 256
                        or ident.strip() != ident or ident in seen or ident in self._seen):
                    raise ValueError('unique bounded stage identity required')
                native._json_value(job)
                seen.add(ident)
            for job in jobs:
                future = self._executor.submit(native._invoke, job)
                self._pending[future] = job['stage_id']
                self._seen.add(job['stage_id'])
            self._peak_in_flight = max(self._peak_in_flight, len(self._pending))
        except BaseException:
            self._fail()
            raise
        finally:
            self._lock.release()

    def receive(self):
        if self._state != 'OPEN' or not self._lock.acquire(blocking=False):
            raise RuntimeError('receive requires an open, exclusively used backend')
        started = time.perf_counter()
        try:
            if not self._pending:
                raise ValueError('no pending worker completion')
            finished, _ = wait(self._pending, return_when=FIRST_COMPLETED)
            result, diagnostics = {}, []
            for future in sorted(finished, key=lambda item: self._pending[item]):
                ident = self._pending[future]
                record, pid, elapsed = future.result()
                native._record(record)
                result[ident] = record
                diagnostics.append({'stage_id':ident,'pid':pid,'wall_s':elapsed})
            for future in finished:
                del self._pending[future]
            for row in diagnostics:
                self._pids.add(row['pid'])
                self._job_timings.append(row)
            self._execute_timings.append({'wall_s':time.perf_counter()-started,
                                          'status':'PASS','job_count':len(result)})
            return result
        except BaseException:
            self._fail()
            raise
        finally:
            self._lock.release()

    def execute(self, jobs):
        if self._pending:
            raise RuntimeError('cannot mix wave dispatch with pending streaming jobs')
        return super().execute(jobs)

    def close(self):
        for future in self._pending:
            future.cancel()
        self._pending.clear()
        super().close()
