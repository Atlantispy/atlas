"""Single full startup preflight; retained R27 policy and all R26 operations."""
from copy import deepcopy
import time
from types import SimpleNamespace
from work.generator_upgrade_r27 import registry as previous
from .preflight import _InvocationSnapshot, clone
from . import provenance as p

snapshot = previous.snapshot
OPERATIONS = previous.OPERATIONS
DEFAULT_ROOT = previous.DEFAULT_ROOT
PLAN_SCHEMA = previous.PLAN_SCHEMA
registration = previous.registration
plan = previous.plan


def run(recipe, *, expected_seconds=None, parallel_threshold_s=120., cache=True,
        cache_root=None, stop_after=None, resume=None, workers=None,
        memory_budget_mb=1024, worker_memory_mb=512, scheduling='ready', startup_budget_s=1.5):
    started = time.perf_counter()
    snapshot.encoded(recipe)
    recipe = deepcopy(recipe)
    sources = p.sources()
    preflight = _InvocationSnapshot(snapshot)
    # R27 privately clones R26.run using the globals of this invocation's
    # namespace. Only snapshot.parse/run change; native producers, executor,
    # worker functions, authenticated store and source identities do not.
    scientific = SimpleNamespace(**dict(vars(previous.previous),snapshot=preflight))
    execute = clone(previous.run, previous=scientific)
    result, primary = None, None
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
                primary.r28_cleanup_errors = [type(error).__name__+': '+str(error)]
            else:
                if result is not None:
                    try:
                        error.snapshot_checkpoint = snapshot.checkpoint(result['graph'])
                    except Exception as checkpoint_error:
                        error.snapshot_checkpoint_error = str(checkpoint_error)
                raise
    result['schema'] = 'diadem.r28-connected-receipt-graph'
    result['preflight'] = dict(preflight.diagnostics,sources=sources)
    result['elapsed_seconds'] = time.perf_counter()-started
    return result
