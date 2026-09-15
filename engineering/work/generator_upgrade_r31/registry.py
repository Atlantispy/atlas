"""R28 preflight/R27 forecasting with six explicitly versioned terrain routes."""
from types import SimpleNamespace
from work.generator_upgrade_r26 import registry as native
from work.generator_upgrade_r27 import registry as forecast
from work.generator_upgrade_r28 import registry as previous
from work.generator_upgrade_r28.preflight import clone
from work.generator_upgrade_r30 import registry as prior
from . import provenance as p, topography

snapshot, OPERATIONS = previous.snapshot, previous.OPERATIONS
DEFAULT_ROOT, PLAN_SCHEMA, plan = previous.DEFAULT_ROOT, previous.PLAN_SCHEMA, previous.plan
_OWNERS = dict(prior._OWNERS, **{operation:topography for operation in topography.OPERATIONS})
_WORKER_REGISTRY = _WORKER_SOURCES = None


def _registration(operation, port, *, cache, cache_root, sources, native_sources, shared):
    if operation not in topography.OPERATIONS:
        return prior._registration(operation, port, cache=cache, cache_root=cache_root,
            sources=sources, native_sources=native_sources, shared=shared)
    snapshot.port(port)
    if port['quantity'] != 'BOUND_COMPONENT_RECEIPT' or port['unit'] != '1':
        raise ValueError('exact source-bound native receipt port required')
    key = 'r26:'+operation
    if key not in shared:
        adapter = topography.Adapter(operation, cache=cache, cache_root=cache_root)
        shared[key] = adapter, adapter.verify
    adapter, check = shared[key]
    signature = native.p.sha({'operation':operation,'port':port,'native_execution':adapter.source_signature})
    def invoke(context, inputs, incoming):
        if set(inputs) & set(incoming):
            raise ValueError('dependency cannot overwrite explicit input')
        result = adapter.run(inputs, incoming)
        if type(result) is not dict:
            raise ValueError('native component receipt must be an object')
        return snapshot.emission(context, {'result':port}, {'result':result},
            evidence='R31 exact topography optimisation; native completeness and authority retained inside receipt',
            source_status='WORKING NON-CANON', status='MODELLED')
    def verify():
        check()
        native.p.verify(sources)
    return {'sha256':native.p.sha({'native_producer':signature,'r26_sources':sources}),
            'run':invoke,'verify':verify}


def registration(operation, port, *, cache=True, cache_root=None):
    return _registration(operation, port, cache=cache,
        cache_root=DEFAULT_ROOT if cache_root is None else cache_root,
        sources=native.p.sources(), native_sources=native.parent.p.sources(), shared={})


def worker_init(specifications, cache, cache_root, orchestration_sources):
    global _WORKER_REGISTRY, _WORKER_SOURCES
    p.verify(orchestration_sources)
    sources, native_sources, shared = native.p.sources(), native.parent.p.sources(), {}
    built = {}
    for operation, spec in specifications.items():
        registered = _registration(operation, spec['port'], cache=cache, cache_root=cache_root,
            sources=sources, native_sources=native_sources, shared=shared)
        if registered['sha256'] != spec['sha256']:
            raise ValueError('R31 worker producer/source signature differs')
        built[operation] = registered
    p.verify(orchestration_sources)
    _WORKER_REGISTRY, _WORKER_SOURCES = built, orchestration_sources


def worker_run(job):
    if _WORKER_REGISTRY is None or _WORKER_SOURCES is None:
        raise ValueError('uninitialised R31 worker')
    p.verify(_WORKER_SOURCES)
    primary = None
    try:
        return native._perform(job, _WORKER_REGISTRY)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            p.verify(_WORKER_SOURCES)
        except BaseException as error:
            if primary is not None:
                primary.r31_worker_cleanup_errors = [str(error)]
            else:
                raise


def run(recipe, **options):
    # Retain the exact R30/R28 execution and clean-up machinery, replacing only
    # its registration/worker namespace. The inherited R30 receipt labels are
    # overwritten below; unrelated scientific producer and c26 keys are not.
    execute = clone(prior.run, p=p, _registration=_registration, _OWNERS=_OWNERS,
                    worker_init=worker_init, worker_run=worker_run)
    result = execute(recipe, **options)
    result['schema'] = 'diadem.r31-connected-receipt-graph'
    result['execution_policy']['scientific_producer_and_cache_version'] = 'R30_EXCEPT_SIX_TOPOGRAPHY_R1_ROUTES'
    result['topography_optimisation'] = {
        'orchestration_sources':result['geology_optimisation']['orchestration_sources'],
        'changed_operations':sorted(topography.OPERATIONS),
        'new_topography_recipe_pins_required':True,
        'old_r22_envelopes_require_explicit_native_import':True,
        'unchanged_operation_cache_keys_preserved':True,
        'new_physical_capability_or_acceptance':False}
    result['geology_optimisation']['changed_operations'] = sorted(prior.geology.OPERATIONS)
    return result
