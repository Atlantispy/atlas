"""Lazy cached geology windows; one bounded worker pool for the regional run.

The caller supplies the complete target graph context and a forward duration
estimate for the requested regional work after anticipated cache reuse. This
constructs fixed geological columns only; windows are not physical boundaries.
Restart the iterator with the same parameters/cache: completed jobs are freshly
authenticated and reused, without trusting an unauthenticated skip cursor.
"""
from copy import deepcopy
from itertools import islice
from types import SimpleNamespace
import time
from work.geology_r1 import working
from work.generator_upgrade_r27.policy import _duration
from work.generator_upgrade_r28.preflight import clone
from . import registry, provenance as p


class _Borrowed:
    def __init__(self, pool):
        self.pool = pool

    def __getattr__(self, name):
        return getattr(self.pool, name)

    def __enter__(self):
        if self.pool._state == 'NEW':
            self.pool.__enter__()
        elif self.pool._state != 'OPEN':
            raise RuntimeError('regional pool is not reusable after close/failure')
        return self

    def close(self):
        # The regional iterator owns shutdown. Every job/window still performs
        # its original before/after source and scientific acceptance checks.
        return None


class _Pool:
    def __init__(self):
        self.pool = self.signature = None

    def factory(self, worker, **options):
        signature = (worker, options['initializer'], deepcopy(options['initargs']),
                     options['workers'], options['memory_budget_mb'], options['worker_memory_mb'])
        if self.pool is None:
            self.pool = registry.native.PoolBackend(worker, **options)
            self.signature = signature
        elif signature != self.signature:
            raise ValueError('regional worker source/resource contract changed between windows')
        return _Borrowed(self.pool)

    def close(self):
        if self.pool is not None:
            self.pool.close()

    def finish_window(self):
        if self.pool is not None:
            if self.pool._pending:
                raise RuntimeError('cannot retire a regional window with pending jobs')
            self.pool._seen.clear()
            self.pool._job_timings.clear()
            self.pool._execute_timings.clear()
            self.pool._peak_in_flight = 0


def recipes(context, *, batch_size=None, window_batches=4, stop_after_batches=None,
            alternative='DEFAULT'):
    """Yield explicit source-pinned graph windows; do not execute their jobs."""
    registry.snapshot.context(context)
    context = deepcopy(context)
    if type(window_batches) is not int or not 1 <= window_batches <= registry.snapshot.MAX_STAGES:
        raise ValueError('window must respect the retained 128-stage graph cap')
    if stop_after_batches is not None and (type(stop_after_batches) is not int or stop_after_batches < 1):
        raise ValueError('positive explicit requested batch count required')
    spec = working.inputs()
    for key in ('world_id', 'snapshot_id', 'spatial_frame_id', 'vertical_reference'):
        expected = spec['context'][key]
        if key == 'snapshot_id' and alternative != 'DEFAULT':
            expected += '/'+alternative
        if context[key] != expected:
            raise ValueError('regional graph context differs from explicit owner input: '+key)
    supports = working.batches(spec, batch_size, alternative)
    if stop_after_batches is not None:
        supports = islice(supports, stop_after_batches)
    port = {'quantity':'BOUND_COMPONENT_RECEIPT', 'unit':'1',
            'support_id':'R18-owner-native-geology-supports',
            'temporal_support':context['snapshot_id']}
    pin = registry.registration('regional_geology', port)['sha256']
    index = 0
    while True:
        window = list(islice(supports, window_batches))
        if not window:
            return
        stages = []
        for support in window:
            stages.append({'stage_id':f'geo-{index:08d}', 'category':'geology',
                'producer_id':'regional_geology', 'producer_sha256':pin,
                'inputs':{'supports':support, 'alternative':alternative,
                          'owner_input_sha256':working.INPUT_SHA},
                'dependencies':{}, 'outputs':{'result':deepcopy(port)}, 'missing_inputs':[],
                'mode':'GENERATED', 'acceptance':{'status':'PENDING',
                'evidence':'Engineering source-bound regional construction; no domain acceptance'}})
            index += 1
        yield {'schema':'diadem.snapshot-graph-recipe.r11', 'context':deepcopy(context),
               'required_categories':['geology'], 'stages':stages,
               'evidence':'Bounded independent geological columns; no coupled terrain or year run'}


def iter_region(context, *, batch_size=None, window_batches=4, stop_after_batches=None,
                alternative='DEFAULT', expected_seconds=None, parallel_threshold_s=120.,
                cache=True, cache_root=None, workers=None, memory_budget_mb=1024,
                worker_memory_mb=512):
    """Yield verified window receipts. Close the iterator if abandoning early.

Expected seconds refers to all requested regional work, not each small window.
Above the threshold the shared pool is selected immediately (resources and at
least two independent ready uncached jobs still constrain actual dispatch).
Pool/source contracts stay fixed across windows; completed cache records remain
usable on restart. Default windows contain four native batches, not a full map.
"""
    estimate = None if expected_seconds is None else _duration(expected_seconds, 'expected_seconds')
    threshold = _duration(parallel_threshold_s, 'parallel_threshold_s', positive=True)
    chosen_workers = 2 if workers is None and estimate is not None and estimate > threshold else workers
    pool = _Pool()
    private_native = SimpleNamespace(**dict(vars(registry.native), PoolBackend=pool.factory))
    execute = clone(registry.run, native=private_native)
    source_binding = p.sources()
    primary = None
    started = time.perf_counter()
    try:
        for number, recipe in enumerate(recipes(context, batch_size=batch_size,
                window_batches=window_batches, stop_after_batches=stop_after_batches,
                alternative=alternative)):
            p.verify(source_binding)
            result = execute(recipe, cache=cache, cache_root=cache_root, workers=chosen_workers,
                             memory_budget_mb=memory_budget_mb, worker_memory_mb=worker_memory_mb,
                             expected_seconds=None, parallel_threshold_s=threshold)
            result['region'] = {'window_index':number,
                'stage_ids':[stage['stage_id'] for stage in recipe['stages']],
                'expected_region_seconds':estimate, 'parallel_threshold_s':threshold,
                'forecast_selected_workers':chosen_workers,
                'estimate_scope':'ALL_REQUESTED_REGIONAL_WORK_AFTER_EXPECTED_REUSE',
                'pool_diagnostics_scope':'CURRENT_WINDOW_TIMINGS_AND_BOUNDED_POOL_PID_SET',
                'elapsed_region_seconds':time.perf_counter()-started,
                'restart':'RESTART_SAME_PARAMETERS_WITH_AUTHENTICATED_STAGE_CACHE',
                'world_or_year_acceptance':False}
            p.verify(source_binding)
            pool.finish_window()
            yield result
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        for check in (pool.close, lambda:p.verify(source_binding)):
            try:
                check()
            except BaseException as error:
                errors.append(str(error))
        if errors:
            if primary is not None and not isinstance(primary, GeneratorExit):
                primary.geology_region_cleanup_errors = errors
            else:
                raise ValueError('regional cleanup failed: '+'; '.join(errors))
