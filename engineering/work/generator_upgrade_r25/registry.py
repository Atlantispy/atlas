"""Cost-aware dispatch over unchanged, explicitly source-bound R24 operations."""
import math
from pathlib import Path
import time
from types import SimpleNamespace
from work.generator_upgrade_r24 import registry as parent
from work.generator_upgrade_r24.parallel import PoolBackend
from . import provenance as p
from .adaptive import AdaptiveBackend

snapshot,executor,Store = parent.snapshot,parent.executor,parent.Store
OPERATIONS = parent.OPERATIONS
DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c25'
_WORKER_REGISTRY = None


def _registration(operation,port,*,cache,cache_root,sources,native_sources,shared):
    base = parent._registration(operation,port,cache=cache,cache_root=cache_root,
        sources=native_sources,shared=shared)
    def verify():
        base['verify']()
        p.verify(sources)
    return {'sha256':p.sha({'r24_producer':base['sha256'],'r25_sources':sources}),
        'run':base['run'],'verify':verify}


def registration(operation,port,*,cache=True,cache_root=None):
    root = DEFAULT_ROOT if cache_root is None else cache_root
    return _registration(operation,port,cache=cache,cache_root=root,
        sources=p.sources(),native_sources=parent.p.sources(),shared={})


def _perform(job,registrations):
    snapshot.exact(job,('stage_id','producer_id','context','inputs','incoming'),'R25 job')
    registered = registrations[job['producer_id']]
    registered['verify']()
    product = registered['run'](job['context'],job['inputs'],job['incoming'])
    registered['verify']()
    return {'product':product,'artifacts':{},'diagnostics':{}}


def worker_init(specifications,cache,cache_root):
    global _WORKER_REGISTRY
    built = {}
    sources,native_sources,shared = p.sources(),parent.p.sources(),{}
    for operation,spec in specifications.items():
        registered = _registration(operation,spec['port'],cache=cache,cache_root=cache_root,
            sources=sources,native_sources=native_sources,shared=shared)
        if registered['sha256'] != spec['sha256']:
            raise ValueError('R25 worker source signature differs')
        built[operation] = registered
    _WORKER_REGISTRY = built


def worker_run(job):
    if _WORKER_REGISTRY is None:
        raise ValueError('uninitialised R25 worker')
    return _perform(job,_WORKER_REGISTRY)


def run(recipe,*,cache=True,cache_root=None,stop_after=None,resume=None,
        workers=None,memory_budget_mb=1024,worker_memory_mb=512,scheduling='ready',
        startup_budget_s=1.5):
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
    if type(startup_budget_s) not in (int,float) or not math.isfinite(startup_budget_s) or startup_budget_s <= 0:
        raise ValueError('positive finite cold startup budget required')
    snapshot.encoded(recipe)
    sources,native_sources,shared = p.sources(),parent.p.sources(),{}
    root = (DEFAULT_ROOT if cache_root is None else Path(cache_root)).resolve()
    registrations,ports = {},{}
    for stage in recipe['stages']:
        if set(stage['outputs']) != {'result'}:
            raise ValueError('one exact receipt output required')
        operation,port = stage['producer_id'],stage['outputs']['result']
        if operation in registrations:
            if ports[operation] != port:
                raise ValueError('same producer with different port binding')
            continue
        ports[operation] = port
        registrations[operation] = _registration(operation,port,cache=cache,cache_root=root,
            sources=sources,native_sources=native_sources,shared=shared)
    namespace = p.sha({'schema':'diadem.stage-local-reuse.r25','r24_sources':native_sources,
                      'r25_sources':sources})
    store = Store(root,namespace) if cache else None
    nodes,order = snapshot.parse(recipe,registrations)
    until = len(order) if stop_after is None else stop_after
    if type(until) is not int or not 0 <= until <= len(order):
        raise ValueError('bounded complete-stage cursor required')
    width = max((len(frontier) for frontier in executor._frontiers(nodes,order[:until],{})),default=0)
    requested = (min(2,width) or 1) if workers is None else workers
    if store is None and resume is not None:
        requested = 1
    pool,adaptive,backend = None,None,None
    graph,primary_error,statistics = None,None,{}
    try:
        if requested > 1 and width > 1:
            specs = {op:{'port':ports[op],'sha256':row['sha256']} for op,row in registrations.items()}
            pool = PoolBackend(worker_run,initializer=worker_init,initargs=(specs,cache,str(root)),
                workers=requested,memory_budget_mb=memory_budget_mb,worker_memory_mb=worker_memory_mb)
            if workers is None:
                if pool.capacity > 1:
                    adaptive = AdaptiveBackend(lambda job:_perform(job,registrations),pool,
                                               startup_budget_s=startup_budget_s)
                    backend = adaptive
            else:
                pool.__enter__()
                backend = pool
            if backend is not None and scheduling == 'wave':
                backend = SimpleNamespace(execute=backend.execute)
        graph = executor.run(snapshot,recipe,registrations,store=store,stop_after=stop_after,
            resume=resume,backend=backend,stats=statistics)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        failures = []
        checks = ([adaptive.close] if adaptive is not None else [pool.close] if pool is not None else [])
        checks += [check for _,check in shared.values()]
        checks += [lambda:parent.p.verify(native_sources),lambda:p.verify(sources)]
        for check in checks:
            try:
                check()
            except BaseException as exc:
                failures.append(exc)
        if failures:
            statistics['completed'] = False
            failure = primary_error if primary_error is not None else failures[0]
            failure.r25_cleanup_errors = [type(exc).__name__+': '+str(exc) for exc in failures]
            if primary_error is None:
                if graph is not None:
                    try:
                        failure.snapshot_checkpoint = snapshot.checkpoint(graph)
                    except Exception as exc:
                        failure.snapshot_checkpoint_error = str(exc)
                raise failure
    execution_backend = adaptive if adaptive is not None else pool
    selection = (adaptive.selection if adaptive is not None else
        {'policy':'EXPLICIT' if workers is not None else 'AUTOMATIC',
         'reason':'explicit worker setting' if workers is not None else 'no independent multi-worker opportunity'})
    return {'schema':'diadem.r25-connected-receipt-graph','graph':graph,
        'elapsed_seconds':time.perf_counter()-started,'execution':statistics,
        'parallel':{'requested_workers':requested,
            'effective_workers':1 if execution_backend is None else execution_backend.effective_workers,
            'worker_pids':[] if execution_backend is None else list(execution_backend.observed_pids),
            'timings':{} if execution_backend is None else execution_backend.timings,
            'scheduling':scheduling,'selection':selection},
        'whole_diadem_year_verified':False,'physical_acceptance_granted':False,
        'scope':'EXECUTABLE_COMPONENT_CONNECTIONS; NATIVE_RESULTS_RETAIN_THEIR_OWN_COMPLETENESS'}
