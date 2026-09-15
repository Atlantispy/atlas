"""R28 execution with an explicitly versioned, faster tectonic snapshot producer."""
from pathlib import Path
import time
from types import SimpleNamespace
from work.generator_upgrade_r26 import registry as native
from work.generator_upgrade_r27 import registry as forecast
from work.generator_upgrade_r28 import registry as previous
from work.generator_upgrade_r28.preflight import clone
from . import provenance as p, tectonics

snapshot = previous.snapshot
OPERATIONS = previous.OPERATIONS
DEFAULT_ROOT = previous.DEFAULT_ROOT
PLAN_SCHEMA = previous.PLAN_SCHEMA
plan = previous.plan
_OWNERS = dict(native._OWNERS,tectonic_snapshot=tectonics)
_registration = clone(native._registration,_OWNERS=_OWNERS)
_WORKER_REGISTRY = None
_WORKER_SOURCES = None

def registration(operation,port,*,cache=True,cache_root=None):
    return _registration(operation,port,cache=cache,
        cache_root=DEFAULT_ROOT if cache_root is None else cache_root,
        sources=native.p.sources(),native_sources=native.parent.p.sources(),shared={})

def worker_init(specifications,cache,cache_root,orchestration_sources):
    global _WORKER_REGISTRY, _WORKER_SOURCES
    p.verify(orchestration_sources)
    sources,native_sources,shared = native.p.sources(),native.parent.p.sources(),{}
    built = {}
    for operation,spec in specifications.items():
        registered = _registration(operation,spec['port'],cache=cache,cache_root=cache_root,
            sources=sources,native_sources=native_sources,shared=shared)
        if registered['sha256'] != spec['sha256']:
            raise ValueError('R29 worker producer/source signature differs')
        built[operation] = registered
    p.verify(orchestration_sources)
    _WORKER_REGISTRY, _WORKER_SOURCES = built, dict(orchestration_sources)

def worker_run(job):
    if _WORKER_REGISTRY is None or _WORKER_SOURCES is None:
        raise ValueError('uninitialised R29 worker')
    p.verify(_WORKER_SOURCES)
    primary = None
    try:
        return native._perform(job,_WORKER_REGISTRY)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            p.verify(_WORKER_SOURCES)
        except BaseException as exc:
            if primary is not None:
                primary.r29_worker_cleanup_errors = [str(exc)]
            else:
                raise

def run(recipe, *, expected_seconds=None, parallel_threshold_s=120., cache=True,
        cache_root=None, stop_after=None, resume=None, workers=None,
        memory_budget_mb=1024, worker_memory_mb=512, scheduling='ready', startup_budget_s=1.5):
    started = time.perf_counter()
    sources = p.sources()
    def pool_factory(worker,**options):
        options['initargs'] = (*options['initargs'],sources)
        return native.PoolBackend(worker,**options)
    scientific = SimpleNamespace(**dict(vars(native),_registration=_registration,
        _OWNERS=_OWNERS,worker_init=worker_init,worker_run=worker_run,PoolBackend=pool_factory))
    forecast_namespace = SimpleNamespace(**dict(vars(forecast),previous=scientific))
    execute = clone(previous.run,previous=forecast_namespace)
    result,primary = None,None
    try:
        result = execute(recipe,expected_seconds=expected_seconds,
            parallel_threshold_s=parallel_threshold_s,cache=cache,cache_root=cache_root,
            stop_after=stop_after,resume=resume,workers=workers,memory_budget_mb=memory_budget_mb,
            worker_memory_mb=worker_memory_mb,scheduling=scheduling,startup_budget_s=startup_budget_s)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            p.verify(sources)
        except BaseException as error:
            if primary is not None:
                primary.r29_cleanup_errors = [str(error)]
            else:
                if result is not None:
                    try:
                        error.snapshot_checkpoint = snapshot.checkpoint(result['graph'])
                    except Exception as checkpoint_error:
                        error.snapshot_checkpoint_error = str(checkpoint_error)
                raise
    result['schema'] = 'diadem.r29-connected-receipt-graph'
    result['execution_policy']['scientific_producer_and_cache_version'] = 'R26_EXCEPT_TECTONIC_SNAPSHOT_R3'
    result['tectonic_optimisation'] = {'orchestration_sources':sources,'changed_operation':'tectonic_snapshot',
        'new_tectonic_recipe_pin_required':True,'unchanged_operation_cache_keys_preserved':True,
        'new_physical_capability_or_acceptance':False}
    result['elapsed_seconds'] = time.perf_counter()-started
    return result
