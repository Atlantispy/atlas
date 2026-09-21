"""R22 operators registered with the existing typed R11/R12 graph machinery.

This adds producers, not a second scheduler. Dependency ordering, source-keyed
reuse and authenticated checkpoint restoration stay in the existing executor.
Receipt ports retain each component's own UNKNOWN/PARTIAL and acceptance flags;
an executed receipt is NOT a claim of completed world generation.
"""
from copy import deepcopy
from pathlib import Path
import time

from work.generator_upgrade_r21 import _snapshot_contract as snapshot
from work.generator_runtime_r12 import executor
from work.generator_runtime_r12.store import Store
from . import provenance as p, species

OPERATIONS = frozenset({'crop_soil', 'moving_roots', 'terrain_from_seed', 'terrain_advance',
    'terrain_view', 'population_reference', 'population_scenario', 'human_service',
    'species_density', 'species_stock', 'species_range', 'species_residence', 'species_recruitment'})


def binding(operation):
    if operation not in OPERATIONS: raise ValueError('unknown R22 implemented operation')
    if operation.startswith('terrain_'):
        from . import terrain
        return terrain._binding()
    return p.identity(moving_ground=operation == 'moving_roots')


def _verify(operation, identity):
    if binding(operation) != identity: raise ValueError('R22 graph producer/source identity changed')


def invoke(operation, arguments, *, cache=True, cache_root=None):
    """Strict named native adapters; no dynamic import/eval or invented inputs."""
    args = deepcopy(arguments)
    if operation == 'crop_soil':
        from . import crop_development
        return crop_development.run(**args, cache=cache, cache_root=cache_root)
    if operation == 'moving_roots':
        from . import moving_roots, evaporation
        engine = args.pop('soil_engine')
        if engine not in ('R13', 'R22_EVAPORATION'): raise ValueError('explicit supported soil engine required')
        root = Path(cache_root) if cache_root is not None else Path(__file__).resolve().parents[2]/'c22'
        store = Store(root.resolve(), p.sha(p.identity(moving_ground=True))) if cache else None
        return moving_roots.run(**args, store=store, soil_backend=evaporation if engine == 'R22_EVAPORATION' else None)
    if operation.startswith('terrain_'):
        from . import terrain
        if operation == 'terrain_advance':
            root = Path(cache_root) if cache_root is not None else Path(__file__).resolve().parents[2]/'c22'
            store = Store(root.resolve(), terrain.cache_namespace(args['envelope'])) if cache else None
            return terrain.advance(**args, store=store)
        return {'terrain_from_seed': terrain.from_seed, 'terrain_advance': terrain.advance,
                'terrain_view': terrain.view}[operation](**args)
    if operation in ('population_reference', 'population_scenario', 'human_service'):
        from . import placement
        return {'population_reference': placement.assign_reference, 'population_scenario': placement.place,
                'human_service': placement.connect_human}[operation](**args, cache=cache, cache_root=cache_root)
    from . import _native_stock as stock, _native_spatial as spatial
    register = species.Registry(args.pop('register_document'))
    register.verify_sources()
    if operation == 'species_density': result = species.run_density(stock, register, **args)
    elif operation == 'species_stock': result = species.run_stock(stock, register, **args)
    elif operation == 'species_range': result = species.run_range(spatial, register, **args)
    elif operation == 'species_residence': result = species.residence_exposure(register, **args)
    elif operation == 'species_recruitment': result = species.recruitment_flux(register, **args)
    else: raise ValueError('unknown R22 operation')
    register.verify_sources()
    return result


def registration(operation, port, *, cache=True, cache_root=None):
    """Receipt ports are typed explicitly; numerical results keep native status."""
    snapshot.port(port)
    if port['quantity'] != 'BOUND_COMPONENT_RECEIPT' or port['unit'] != '1':
        raise ValueError('R22 native receipt port required, not an invented scalar quantity')
    identity = binding(operation)
    signature = p.sha({'operation': operation, 'port': port, 'execution': identity})
    def run(context, inputs, dependencies):
        if set(inputs) & set(dependencies): raise ValueError('dependency cannot overwrite explicit input')
        result = invoke(operation, {**inputs, **dependencies}, cache=cache, cache_root=cache_root)
        if type(result) is not dict: raise ValueError('component receipt must be an object')
        # Wall times, cache hits and reuse counters are execution diagnostics,
        # not deterministic scientific receipt values for dependency identities.
        if operation in ('moving_roots', 'crop_soil'):
            result.pop('execution', None)
        elif operation in ('terrain_from_seed', 'terrain_advance'):
            result['execution'] = {k: v for k, v in result['execution'].items()
                                   if k not in ('cache_hit', 'cache_key')}
        return snapshot.emission(context, {'result': port}, {'result': result},
            evidence='R22 executed component receipt; native status and acceptance remain inside receipt',
            source_status='WORKING NON-CANON', status='MODELLED')
    return {'sha256': signature, 'run': run, 'verify': lambda: _verify(operation, identity)}


def run(recipe, *, cache=True, cache_root=None, stop_after=None, resume=None):
    """Run a caller-declared existing snapshot recipe, caching completed nodes."""
    start = time.perf_counter()
    snapshot.encoded(recipe)
    registrations = {}
    for stage in recipe['stages']:
        if set(stage['outputs']) != {'result'}:
            raise ValueError('one exact R22 receipt output required')
        operation = stage['producer_id']
        registered = registration(operation, stage['outputs']['result'], cache=cache, cache_root=cache_root)
        if operation in registrations and registered['sha256'] != registrations[operation]['sha256']:
            raise ValueError('same producer name with different port binding; use matching receipt support')
        registrations[operation] = registered
    namespace = p.sha({key: value['sha256'] for key, value in sorted(registrations.items())})
    root = Path(cache_root) if cache_root is not None else Path(__file__).resolve().parents[2]/'c22'
    store = Store(root.resolve(), namespace) if cache else None
    statistics = {}
    result = executor.run(snapshot, recipe, registrations, store=store,
        stop_after=stop_after, resume=resume, stats=statistics,
        **species.source_hooks(recipe))
    return {'schema': 'diadem.r22-connected-receipt-graph', 'graph': result,
        'elapsed_seconds': time.perf_counter()-start, 'execution': statistics,
        'whole_diadem_year_verified': False, 'physical_acceptance_granted': False,
        'scope': 'EXECUTABLE_COMPONENT_CONNECTIONS; NATIVE_RESULTS_RETAIN_THEIR_OWN_COMPLETENESS'}
