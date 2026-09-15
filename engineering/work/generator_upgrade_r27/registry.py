"""Forecast-directed scheduling over the unchanged R26 producers and cache.

Only dispatch policy changes. R26 recipes, exact producer pins, scientific
products and authenticated cache namespaces remain valid and unchanged.
"""
from copy import deepcopy
import time
from types import FunctionType
from work.generator_upgrade_r26 import registry as previous
from . import provenance as p
from .policy import ForecastBackend, _duration

snapshot = previous.snapshot
OPERATIONS = previous.OPERATIONS
DEFAULT_ROOT = previous.DEFAULT_ROOT
PLAN_SCHEMA = 'diadem.execution-plan.r27'
registration = previous.registration


def _seconds(value, name, *, optional=False, positive=False):
    if value is None and optional:
        return None
    return _duration(value,name,positive=positive)


def plan(recipe, expected_seconds):
    """A forecast is execution metadata, never a scientific input or cache key.

Estimate serial seconds of the requested work after expected reuse; adjust the
estimate for stop_after/resume. This is not a measured duration or a guarantee.
"""
    result = {'schema':PLAN_SCHEMA,'recipe':deepcopy(recipe),
        'expected_seconds':_seconds(expected_seconds,'expected_seconds',optional=True)}
    snapshot.encoded(result)
    return result


def run(recipe, *, expected_seconds=None, parallel_threshold_s=120., cache=True,
        cache_root=None, stop_after=None, resume=None, workers=None,
        memory_budget_mb=1024, worker_memory_mb=512, scheduling='ready', startup_budget_s=1.5):
    started = time.perf_counter()
    snapshot.encoded(recipe)
    if type(recipe) is dict and recipe.get('schema') == PLAN_SCHEMA:
        snapshot.exact(recipe,('schema','recipe','expected_seconds'),'R27 execution plan')
        if expected_seconds is not None:
            raise ValueError('forecast supplied twice; choose execution plan or argument')
        expected_seconds = recipe['expected_seconds']
        recipe = recipe['recipe']
    estimate = _seconds(expected_seconds,'expected_seconds',optional=True)
    threshold = _seconds(parallel_threshold_s,'parallel_threshold_s',positive=True)
    sources = p.sources()
    def factory(local_worker,pool,**options):
        return ForecastBackend(local_worker,pool,expected_seconds=estimate,
            parallel_threshold_s=threshold,**options)
    # Private function globals only. No monkeypatch of the retained public
    # runner, workers, numerical modules, callbacks or cache implementation.
    namespace = dict(vars(previous),AdaptiveBackend=factory)
    execute = FunctionType(previous.run.__code__,namespace,previous.run.__name__,
        previous.run.__defaults__,previous.run.__closure__)
    execute.__kwdefaults__ = previous.run.__kwdefaults__.copy()
    result,primary = None,None
    try:
        result = execute(recipe,cache=cache,cache_root=cache_root,stop_after=stop_after,
            resume=resume,workers=workers,memory_budget_mb=memory_budget_mb,
            worker_memory_mb=worker_memory_mb,scheduling=scheduling,startup_budget_s=startup_budget_s)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            p.verify(sources)
        except BaseException as error:
            if primary is not None:
                primary.r27_cleanup_errors = [type(error).__name__+': '+str(error)]
            else:
                if result is not None:
                    try:
                        error.snapshot_checkpoint = snapshot.checkpoint(result['graph'])
                    except Exception as checkpoint_error:
                        error.snapshot_checkpoint_error = str(checkpoint_error)
                raise
    result['schema'] = 'diadem.r27-connected-receipt-graph'
    result['elapsed_seconds'] = time.perf_counter()-started
    result['execution_policy'] = {
        'schema':'diadem.forecast-policy.r27','expected_seconds':estimate,
        'parallel_threshold_s':threshold,'estimate_basis':'CALLER_PLANNED_SERIAL_SECONDS_AFTER_EXPECTED_REUSE',
        'estimate_is_measured':False,'required_prerequisite_runs':0,
        'explicit_workers_override':workers is not None,'sources':sources,
        'scientific_producer_and_cache_version':'R26_UNCHANGED',
        'automatic_native_job_splitting':False}
    return result
