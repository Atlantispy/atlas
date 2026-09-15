"""R22 scientific producers on the unchanged executor with cheaper source checks.

Compile source-check structure, never source-file digests. Each execution/cache
boundary still reads and hashes current bytes. Native moving-ground/terrain
bindings use the original verifier, not an unsupported fast-path approximation.
"""
from pathlib import Path
import time
from work.generator_upgrade_r22 import registry as native
from work.generator_upgrade_r21 import _snapshot_contract as snapshot
from work.generator_runtime_r12 import executor
from . import provenance as p
from .storage import Store
from .verification import Binding

OPERATIONS = native.OPERATIONS
DEFAULT_ROOT = Path(__file__).resolve().parents[2]/'c23'


def _registration(operation, port, *, cache, cache_root, local_sources, shared=None):
    snapshot.port(port)
    if port['quantity'] != 'BOUND_COMPONENT_RECEIPT' or port['unit'] != '1':
        raise ValueError('R23 native receipt port required')
    if operation not in OPERATIONS:
        raise ValueError('unknown R23 implemented operation')
    local = dict(local_sources)
    shared = {} if shared is None else shared
    # These are exactly the three source closures in R22.binding, not inferred
    # scientific independence. Per-stage checks are still performed each time.
    family = ('terrain' if operation.startswith('terrain_') else
              'moving' if operation == 'moving_roots' else 'ordinary')
    accelerated = family == 'ordinary'
    if family not in shared:
        identity = native.binding(operation)  # Full original entry check.
        verifier = Binding(identity, extra_sources=local,
            extra_inventory={str(p.HERE): sorted(local)}) if accelerated else None

        def verify():
            if verifier is not None:
                verifier.verify()
            else:
                p.verify(local)
                if native.binding(operation) != identity:
                    raise ValueError('R23 native producer binding changed')

        def verify_full():
            p.verify(local)
            if native.binding(operation) != identity:
                raise ValueError('R23 final original producer binding changed')
        shared[family] = (identity, verify, verify_full)
    identity, verify, verify_full = shared[family]
    signature = p.sha({'operation': operation, 'port': port,
        'execution': identity, 'r23_sources': local})

    def run(context, inputs, dependencies):
        if set(inputs) & set(dependencies):
            raise ValueError('dependency cannot overwrite explicit input')
        result = native.invoke(operation, {**inputs, **dependencies}, cache=cache,
            cache_root=DEFAULT_ROOT if cache_root is None else cache_root)
        if type(result) is not dict:
            raise ValueError('component receipt must be an object')
        # Same scientific receipt as R22; timing/cache counters stay separate.
        if operation in ('moving_roots', 'crop_soil'):
            result.pop('execution', None)
        elif operation in ('terrain_from_seed', 'terrain_advance'):
            result['execution'] = {k: v for k, v in result['execution'].items()
                                   if k not in ('cache_hit', 'cache_key')}
        return snapshot.emission(context, {'result': port}, {'result': result},
            evidence='R22 executed component receipt; native status and acceptance remain inside receipt',
            source_status='WORKING NON-CANON', status='MODELLED')

    return {'sha256': signature, 'run': run, 'verify': verify}, verify_full, accelerated


def registration(operation, port, *, cache=True, cache_root=None):
    return _registration(operation, port, cache=cache, cache_root=cache_root,
                         local_sources=p.sources())[0]


def run(recipe, *, cache=True, cache_root=None, stop_after=None, resume=None):
    start = time.perf_counter()
    snapshot.encoded(recipe)
    local = p.sources()
    registrations, ports, shared, compiled = {}, {}, {}, []
    for stage in recipe['stages']:
        if set(stage['outputs']) != {'result'}:
            raise ValueError('one exact R23 receipt output required')
        operation = stage['producer_id']
        port = stage['outputs']['result']
        encoded_port = snapshot.encoded(port)
        if operation in registrations:
            if ports[operation] != encoded_port:
                raise ValueError('same producer name with different port binding')
            continue
        ports[operation] = encoded_port
        registered, final_check, accelerated = _registration(operation, port,
            cache=cache, cache_root=cache_root, local_sources=local, shared=shared)
        registrations[operation] = registered
        if accelerated:
            compiled.append(operation)
    namespace = p.sha({key: value['sha256'] for key, value in sorted(registrations.items())})
    root = DEFAULT_ROOT if cache_root is None else Path(cache_root)
    store = Store(root.resolve(), namespace) if cache else None
    statistics = {}
    try:
        result = executor.run(snapshot, recipe, registrations, store=store,
            stop_after=stop_after, resume=resume, stats=statistics)
    finally:
        # Keep a full original closure comparison at the call boundary as well.
        for _, _, final_check in shared.values():
            final_check()
        p.verify(local)
    return {'schema': 'diadem.r23-connected-receipt-graph', 'graph': result,
        'elapsed_seconds': time.perf_counter()-start, 'execution': statistics,
        'optimisation': {'unique_registrations': len(registrations),
            'unique_source_bindings': len(shared),
            'compiled_source_producers': sorted(compiled)},
        'whole_diadem_year_verified': False, 'physical_acceptance_granted': False,
        'scope': 'EXECUTABLE_COMPONENT_CONNECTIONS; NATIVE_RESULTS_RETAIN_THEIR_OWN_COMPLETENESS'}
