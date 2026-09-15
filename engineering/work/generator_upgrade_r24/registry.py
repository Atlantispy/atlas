"""All R22 operations with inner reuse, selective graph cache and bounded workers."""
from pathlib import Path
import time
from work.generator_upgrade_r22 import registry as native
from work.generator_upgrade_r21 import _snapshot_contract as snapshot
from work.generator_upgrade_r23.verification import Binding
from . import executor, provenance as p, verification
from .inner import Adapter
from .storage import Store

OPERATIONS = native.OPERATIONS
DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c24'


def _registration(operation, port, *, cache, cache_root, sources, shared):
    snapshot.port(port)
    if (operation not in OPERATIONS or port['quantity'] != 'BOUND_COMPONENT_RECEIPT'
            or port['unit'] != '1'):
        raise ValueError('implemented R24 operation and exact receipt port required')
    family = ('terrain' if operation.startswith('terrain_') else
              'moving' if operation == 'moving_roots' else 'ordinary')
    if family not in shared:
        identity = verification.native_binding(operation)
        if family == 'ordinary':
            inventories = {str(root):sorted(path for path in sources if Path(path).parent == root)
                           for root in (p.HERE,p.PREVIOUS)}
            compiled = Binding(identity, extra_sources=sources, extra_inventory=inventories)
            compiled._prefixes += ('work.generator_upgrade_r24',)
            def check():
                compiled.verify()
        else:
            def check():
                verification.verify_native(operation, identity)
                p.verify(sources)
        shared[family] = identity, check
    identity, check = shared[family]
    signature = p.sha({'operation':operation,'port':port,
        'execution':identity,'r24_sources':sources})
    adapter = None

    def run(context, inputs, dependencies):
        nonlocal adapter
        if set(inputs) & set(dependencies):
            raise ValueError('dependency cannot overwrite explicit input')
        # A verified outer-cache hit never enters the native stage, so it does
        # not need to construct that stage's private inner cache machinery.
        if adapter is None:
            adapter = Adapter(operation,binding=identity,verify=check,adapter_sources=sources)
        result = adapter.invoke({**inputs,**dependencies},cache=cache,cache_root=cache_root)
        if type(result) is not dict:
            raise ValueError('component receipt must be an object')
        if operation in ('crop_soil','moving_roots'):
            result.pop('execution',None)
        elif operation in ('terrain_from_seed','terrain_advance'):
            result['execution'] = {key:value for key,value in result['execution'].items()
                                   if key not in ('cache_hit','cache_key')}
        return snapshot.emission(context,{'result':port},{'result':result},
            evidence='R22 executed component receipt; native status and acceptance remain inside receipt',
            source_status='WORKING NON-CANON',status='MODELLED')
    return {'sha256':signature,'run':run,'verify':check}


def registration(operation, port, *, cache=True, cache_root=None):
    return _registration(operation,port,cache=cache,cache_root=cache_root,
                         sources=p.sources(),shared={})


def run(recipe, *, cache=True, cache_root=None, stop_after=None, resume=None,
        workers=None, memory_budget_mb=1024, worker_memory_mb=512, scheduling='ready'):
    started = time.perf_counter()
    if workers is not None and (type(workers) is not int or workers < 1):
        raise ValueError('workers must be a positive integer or automatic None')
    if scheduling not in ('ready','wave'):
        raise ValueError('explicit ready or wave scheduling required')
    for name,value in (('memory_budget_mb',memory_budget_mb),('worker_memory_mb',worker_memory_mb)):
        if type(value) is not int or value < 1:
            raise ValueError(name+' must be a positive integer')
    if memory_budget_mb < worker_memory_mb:
        raise ValueError('memory budget cannot accommodate one estimated worker')
    snapshot.encoded(recipe)
    sources = p.sources()
    registrations,ports,shared = {},{},{}
    for stage in recipe['stages']:
        if set(stage['outputs']) != {'result'}:
            raise ValueError('one exact receipt output required')
        operation,port = stage['producer_id'],stage['outputs']['result']
        key = snapshot.encoded(port)
        if operation in registrations:
            if ports[operation] != key:
                raise ValueError('same producer with different port binding')
            continue
        ports[operation] = key
        registrations[operation] = _registration(operation,port,cache=cache,
            cache_root=cache_root,sources=sources,shared=shared)
    # Every invocation key already binds its stage, producer source hash and
    # dependency products. Unrelated graph producers need not salt its directory.
    namespace = p.sha({'schema':'diadem.stage-local-reuse.r24','runtime_sources':sources})
    root = DEFAULT_ROOT if cache_root is None else Path(cache_root)
    store = Store(root.resolve(),namespace) if cache else None
    # Auto only starts a pool when this bounded graph contains independent work.
    # Explicit one-worker mode retains zero process-startup overhead.
    nodes,order = snapshot.parse(recipe,registrations)
    until = len(order) if stop_after is None else stop_after
    if type(until) is not int or not 0 <= until <= len(order):
        raise ValueError('bounded complete-stage cursor required')
    remaining = order[:until]
    width = max((len(frontier) for frontier in executor._frontiers(nodes,remaining,{})),default=0)
    requested = (min(2,width) or 1) if workers is None else workers
    if store is None and resume is not None:
        requested = 1  # Original semantic replay explicitly stays serial.
    pool = None
    graph, primary_error = None, None
    statistics = {}
    try:
        if requested > 1 and width > 1:
            from .parallel import PoolBackend, worker_init, worker_run
            specs = {op:{'port':next(stage['outputs']['result'] for stage in recipe['stages']
                if stage['producer_id']==op),'sha256':row['sha256']} for op,row in registrations.items()}
            pool = PoolBackend(worker_run,initializer=worker_init,
                initargs=(specs,cache,str(root.resolve())),workers=requested,
                memory_budget_mb=memory_budget_mb,worker_memory_mb=worker_memory_mb)
            pool.__enter__()
        backend = pool
        if pool is not None and scheduling == 'wave':
            from types import SimpleNamespace
            backend = SimpleNamespace(execute=pool.execute)
        graph = executor.run(snapshot,recipe,registrations,store=store,
            stop_after=stop_after,resume=resume,backend=backend,stats=statistics)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        # A cleanup/source failure must not erase the original error or its
        # authenticated-prefix checkpoint. Still perform every final check.
        failures = []
        checks = ([pool.close] if pool is not None else [])
        checks += [check for _,check in shared.values()] + [lambda: p.verify(sources)]
        for check in checks:
            try:
                check()
            except BaseException as exc:
                failures.append(exc)
        if failures:
            statistics['completed'] = False
            failure = primary_error if primary_error is not None else failures[0]
            failure.r24_cleanup_errors = [type(exc).__name__+': '+str(exc) for exc in failures]
            if primary_error is None:
                if graph is not None:
                    try:
                        failure.snapshot_checkpoint = snapshot.checkpoint(graph)
                    except Exception as exc:
                        failure.snapshot_checkpoint_error = str(exc)
                raise failure
    return {'schema':'diadem.r24-connected-receipt-graph','graph':graph,
        'elapsed_seconds':time.perf_counter()-started,'execution':statistics,
        'parallel':{'requested_workers':requested,'effective_workers':1 if pool is None else pool.effective_workers,
            'worker_pids':[] if pool is None else list(pool.observed_pids),
            'timings':{} if pool is None else pool.timings,'scheduling':scheduling},
        'whole_diadem_year_verified':False,'physical_acceptance_granted':False,
        'scope':'EXECUTABLE_COMPONENT_CONNECTIONS; NATIVE_RESULTS_RETAIN_THEIR_OWN_COMPLETENESS'}
