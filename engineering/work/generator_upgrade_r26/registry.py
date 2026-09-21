"""Cost-aware dispatch over unchanged, explicitly source-bound R24 operations."""
import math
from pathlib import Path
import time
from types import SimpleNamespace
from work.generator_upgrade_r24 import registry as parent
from work.generator_upgrade_r24.parallel import PoolBackend
from . import provenance as p
from work.generator_upgrade_r25.adaptive import AdaptiveBackend

snapshot,executor,Store = parent.snapshot,parent.executor,parent.Store
# Category coverage is explicit; a producer cannot masquerade as another category.
LEGACY_CATEGORIES = {
    'crop_soil':('land_use_agriculture','soils_ground_conditions'),
    'moving_roots':('soils_ground_conditions','erosion_sediment_transport'),
    'terrain_from_seed':('topography_topology',),
    'terrain_advance':('topography_topology','erosion_sediment_transport','hydrology'),
    'terrain_view':('topography_topology',),
    'population_reference':('populations',),
    'population_scenario':('populations',),
    'human_service':('infrastructure_connectivity',),
    'species_density':('plant_animal_ranges',),
    'species_stock':('plant_animal_ranges',),
    'species_range':('plant_animal_ranges',),
    'species_residence':('plant_animal_ranges',),
    'species_recruitment':('plant_animal_ranges',),
}


def catalogue():
    from . import physical, environment, social, human
    categories, owners = dict(LEGACY_CATEGORIES), {}
    for module in (physical,environment,social,human):
        for operation, covered in module.OPERATIONS.items():
            if operation in categories or not covered or any(c not in snapshot.CATEGORIES for c in covered):
                raise ValueError('duplicate operation or invalid category coverage')
            categories[operation],owners[operation] = tuple(covered),module
    return categories,owners


# Evaluated after all native family modules have been loaded and source captured.
OPERATIONS, _OWNERS = catalogue()
DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c26'
_WORKER_REGISTRY = None


def _registration(operation,port,*,cache,cache_root,sources,native_sources,shared):
    snapshot.port(port)
    if operation not in OPERATIONS or port['quantity'] != 'BOUND_COMPONENT_RECEIPT' or port['unit'] != '1':
        raise ValueError('implemented R26 operation and exact receipt port required')
    if operation in parent.OPERATIONS:
        base = parent._registration(operation,port,cache=cache,cache_root=cache_root,
            sources=native_sources,shared=shared)
    else:
        key = 'r26:'+operation
        if key not in shared:
            if 'adapter_context' not in shared:
                shared['adapter_context'] = {},lambda:None
            adapter = _OWNERS[operation].Adapter(operation,cache=cache,cache_root=cache_root,
                shared=shared['adapter_context'][0])
            shared[key] = adapter,adapter.verify
        adapter,check = shared[key]
        signature = p.sha({'operation':operation,'port':port,'native_execution':adapter.source_signature})
        def invoke(context, inputs, incoming):
            if set(inputs) & set(incoming):
                raise ValueError('dependency cannot overwrite explicit input')
            result = adapter.run(inputs,incoming)
            if type(result) is not dict:
                raise ValueError('native component receipt must be an object')
            return snapshot.emission(context,{'result':port},{'result':result},
                evidence='R26 native component execution; native completeness and authority retained inside receipt',
                source_status='WORKING NON-CANON',status='MODELLED')
        base = {'sha256':signature,'run':invoke,'verify':check}
    def verify():
        base['verify']()
        p.verify(sources)
    return {'sha256':p.sha({'native_producer':base['sha256'],'r26_sources':sources}),
        'run':base['run'],'verify':verify}


def registration(operation,port,*,cache=True,cache_root=None):
    root = DEFAULT_ROOT if cache_root is None else cache_root
    return _registration(operation,port,cache=cache,cache_root=root,
        sources=p.sources(),native_sources=parent.p.sources(),shared={})


def _perform(job,registrations):
    snapshot.exact(job,('stage_id','producer_id','context','inputs','incoming'),'R26 job')
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
            raise ValueError('R26 worker source signature differs')
        built[operation] = registered
    _WORKER_REGISTRY = built


def worker_run(job):
    if _WORKER_REGISTRY is None:
        raise ValueError('uninitialised R26 worker')
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
        if operation not in OPERATIONS or stage['category'] not in OPERATIONS[operation]:
            raise ValueError('category is not implemented by this producer: '+str(operation))
        if operation in registrations:
            if ports[operation] != port:
                raise ValueError('same producer with different port binding')
            continue
        ports[operation] = port
        registrations[operation] = _registration(operation,port,cache=cache,cache_root=root,
            sources=sources,native_sources=native_sources,shared=shared)
    namespace = p.sha({'schema':'diadem.stage-local-reuse.r26','r24_sources':native_sources,
                      'r26_sources':sources})
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
        # Native external-file validation must also run on outer cache hits.
        # Values are installed only after the executor's full record validation.
        accepted_values = {}
        def validate_native(ident,row):
            stage = nodes[ident]
            if row['producer_executed'] and stage['producer_id'] in _OWNERS:
                adapter = shared['r26:'+stage['producer_id']][0]
                check_result = getattr(adapter,'validate_result',None)
                if check_result is not None:
                    incoming = {name:accepted_values[dep['stage_id']][dep['output']]
                        for name,dep in stage['dependencies'].items()}
                    check_result(row['product']['values']['result'],stage['inputs'],incoming)
            accepted_values[ident] = row['product']['values']
        def restored(ident,record):
            if record['artifacts'] or record['diagnostics']:
                raise ValueError('undeclared R26 side artifacts')
            validate_native(ident,record['row'])
        def computed(ident,row):
            validate_native(ident,row)
            return {'artifacts':{},'diagnostics':{}}
        graph = executor.run(snapshot,recipe,registrations,store=store,stop_after=stop_after,
            resume=resume,backend=backend,stats=statistics,
            **parent.source_hooks(recipe,on_restore=restored,on_computed=computed))
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
            failure.r26_cleanup_errors = [type(exc).__name__+': '+str(exc) for exc in failures]
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
    return {'schema':'diadem.r26-connected-receipt-graph','graph':graph,
        'elapsed_seconds':time.perf_counter()-started,'execution':statistics,
        'parallel':{'requested_workers':requested,
            'effective_workers':1 if execution_backend is None else execution_backend.effective_workers,
            'worker_pids':[] if execution_backend is None else list(execution_backend.observed_pids),
            'timings':{} if execution_backend is None else execution_backend.timings,
            'scheduling':scheduling,'selection':selection},
        'whole_diadem_year_verified':False,'physical_acceptance_granted':False,
        'scope':'EXECUTABLE_COMPONENT_CONNECTIONS; NATIVE_RESULTS_RETAIN_THEIR_OWN_COMPLETENESS'}
