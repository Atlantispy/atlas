"""Run unchanged R11 producers with explicit R12 execution provenance.

Only private function-global copies are adapted. Neither sealed source bytes nor
the protected module objects are modified. Scientific results retain their exact
R11 identity; actual execution/reuse accounting is a separate R12 envelope.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
from pathlib import Path
import time
import types

from . import executor, parents, provenance
from .parallel import PoolBackend
from .store import Store

DEFAULT_DECODED_BYTES = 32 * 1024 * 1024
_WORKER = None


def adapted(function, **overrides):
    namespace = dict(function.__globals__)
    namespace.update(overrides)
    clone = types.FunctionType(function.__code__, namespace, function.__name__,
                               function.__defaults__, function.__closure__)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone


def cached_artifacts(base, *, max_bytes=DEFAULT_DECODED_BYTES):
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError('nonnegative decoded-byte budget required')

    class CachedArtifacts(base):
        def __init__(self, codec):
            super().__init__(codec)
            self._decoded = OrderedDict()
            self._bytes = 0
            self.decode_stats = {'hits': 0, 'misses': 0, 'evictions': 0,
                                 'max_accounted_bytes': 0, 'budget_bytes': max_bytes}

        def get(self, ref):
            # Validate the reference and the current encoded record on every
            # access. A mutated dictionary cannot bypass decoding checks.
            fields = {'artifact_id', 'sha256', 'schema', 'byte_length', 'role'}
            if type(ref) is not dict or set(ref) != fields:
                raise ValueError('exact artifact reference required')
            if type(ref['role']) is not str or not ref['role'].strip() or len(ref['role']) > 4096:
                raise ValueError('bounded artifact role required')
            key = ref['artifact_id']
            if key != ref['sha256'] or key not in self.records:
                raise ValueError('unbound scientific artifact')
            record = self.records[key]
            if record.get('sha256') != key or record.get('byte_length') != ref['byte_length']:
                raise ValueError('artifact identity/size differs')
            raw = provenance.encoded(record)
            if len(raw) > provenance.LIMIT:
                raise ValueError('bounded packed artifact required')
            signature = hashlib.sha256(raw).hexdigest()
            cached = self._decoded.get(key)
            if cached is not None and cached[0] == signature:
                value = cached[1]
                if value.get('schema', 'explicit-object') != ref['schema']:
                    raise ValueError('artifact scientific schema differs')
                self._decoded.move_to_end(key)
                self.decode_stats['hits'] += 1
                return deepcopy(value)
            value = super().get(ref)
            self.decode_stats['misses'] += 1
            if cached is not None:
                self._bytes -= self._decoded.pop(key)[2]
            # Charge four times canonical bytes for Python object overhead.
            # This is an accounting budget, not a claimed OS RSS hard limit.
            size = 4 * ref['byte_length']
            if size <= max_bytes:
                while self._decoded and self._bytes + size > max_bytes:
                    _, old = self._decoded.popitem(last=False)
                    self._bytes -= old[2]
                    self.decode_stats['evictions'] += 1
                self._decoded[key] = (signature, deepcopy(value), size)
                self._bytes += size
                self.decode_stats['max_accounted_bytes'] = max(
                    self.decode_stats['max_accounted_bytes'], self._bytes)
            return value

    return CachedArtifacts


def assemble(bundle, recipe, *, supplied_parent=None, decoded_bytes=DEFAULT_DECODED_BYTES):
    workflow = bundle.module('workflow')
    build = adapted(workflow.assemble,
                    Artifacts=cached_artifacts(workflow.Artifacts, max_bytes=decoded_bytes))
    return build(bundle, recipe, supplied_parent=supplied_parent)


def collect(built, ident, row):
    refs = []
    if row['product']['status'] != 'UNKNOWN':
        refs.append(row['product']['values']['product'])
    diagnostics = {}
    if ident in built['diagnostics']:
        diagnostics[ident] = deepcopy(built['diagnostics'][ident])
        refs.append(diagnostics[ident])
    records = {ref['artifact_id']: deepcopy(built['artifacts'].records[ref['artifact_id']])
               for ref in refs}
    return {'artifacts': records, 'diagnostics': diagnostics}


def restore(built, ident, entry):
    artifacts = built['artifacts']
    refs = []
    product = entry['row']['product']
    if product['status'] != 'UNKNOWN':
        refs.append(product['values']['product'])
    diagnostics = entry['diagnostics']
    if set(diagnostics) - {ident}:
        raise ValueError('another stage cannot replace diagnostic evidence')
    refs.extend(diagnostics.values())
    if set(entry['artifacts']) != {ref['artifact_id'] for ref in refs}:
        raise ValueError('exact restored scientific unit inventory required')
    for key, record in entry['artifacts'].items():
        if key != record.get('sha256'):
            raise ValueError('restored artifact key differs')
        artifacts.codec.unpack(record)
        if key in artifacts.records and artifacts.records[key] != record:
            raise ValueError('restored artifact collision')
        artifacts.records[key] = deepcopy(record)
    for ref in refs:
        artifacts.get(ref)
    for key, ref in diagnostics.items():
        if key in built['diagnostics'] and built['diagnostics'][key] != ref:
            raise ValueError('restored diagnostic collision')
        built['diagnostics'][key] = deepcopy(ref)


def worker_init(recipe, supplied_parent, identity, decoded_bytes, cache_root):
    global _WORKER
    bundle = provenance.load_science()
    provenance.verify_execution(bundle, identity)
    built = assemble(bundle, recipe, supplied_parent=supplied_parent, decoded_bytes=decoded_bytes)
    nodes, _ = bundle.module('snapshot').parse(built['recipe'], built['registry'])
    cache = None if cache_root is None else Store(Path(cache_root), provenance.sha(identity))
    _WORKER = {'bundle': bundle, 'built': built, 'identity': identity, 'cache': cache, 'nodes': nodes}


def worker_run(job):
    if _WORKER is None:
        raise ValueError('bound scientific worker not initialised')
    bundle = _WORKER['bundle']
    built = _WORKER['built']
    provenance.verify_execution(bundle, _WORKER['identity'], full=False)
    ident = job['stage_id']
    nodes = _WORKER['nodes']
    if ident not in nodes or job['producer_id'] != nodes[ident]['producer_id']:
        raise ValueError('undeclared worker producer')
    if job['context'] != built['recipe']['context'] or job['inputs'] != nodes[ident]['inputs']:
        raise ValueError('worker stage input/context differs')
    expected = {ref['artifact_id'] for ref in job['incoming'].values()}
    if set(job['records']) != expected:
        raise ValueError('worker requires exact incoming scientific units')
    artifacts = built['artifacts']
    for key, record in job['records'].items():
        if key != record.get('sha256'):
            raise ValueError('worker artifact key differs')
        artifacts.codec.unpack(record)
        if key in artifacts.records and artifacts.records[key] != record:
            raise ValueError('worker scientific artifact collision')
        artifacts.records[key] = deepcopy(record)
    producer = built['registry'][job['producer_id']]
    producer['verify']()
    parent_stats = {}
    with parents.reuse(bundle, _WORKER['cache'], parent_stats):
        product = producer['run'](deepcopy(job['context']), deepcopy(job['inputs']), deepcopy(job['incoming']))
    producer['verify']()
    provenance.verify_execution(bundle, _WORKER['identity'], full=False)
    extras = collect(built, ident, {'product': product})
    # Auxiliary accounting travels outside the exact scientific payload.
    _WORKER['last_parent_stats'] = parent_stats
    return {'product': deepcopy(product), **extras}


class ArtifactBackend:
    def __init__(self, pool, built):
        self.pool, self.built = pool, built

    def execute(self, jobs):
        def enriched(job):
            records = {ref['artifact_id']: self.built['artifacts'].records[ref['artifact_id']]
                       for ref in job['incoming'].values()}
            return {**job, 'records': records}
        return self.pool.execute([enriched(job) for job in jobs])


class SnapshotAdapter:
    def __init__(self, original, run):
        self.original, self.run = original, run

    def __getattr__(self, name):
        return getattr(self.original, name)


def cache_warnings(stats):
    """Summarise observed coordinator skips, never uncollected worker totals."""
    if stats is None:
        return []
    messages = (
        ('skipped_full', 'CACHE_CAPACITY', 'the configured cache capacity would be exceeded'),
        ('skipped_oversize', 'CACHE_RECORD_SIZE', 'the result or record exceeded the per-record size limit'))
    return [{'code': code, 'skipped_writes': stats.get(key, 0),
             'scope': 'COORDINATOR_STORE_INSTANCE_ONLY',
             'message': 'Main-process cache skipped ' + str(stats[key]) + ' write(s) because ' + reason
                        + '. Those results may need recomputing; existing cache files were kept.'}
            for key, code, reason in messages if stats.get(key, 0) > 0]


def validate_options(*, workers=1, memory_budget_mb=1024, worker_memory_mb=512,
                     stop_after=None, decoded_bytes=DEFAULT_DECODED_BYTES):
    """Cheap shared API/CLI checks, before source loading or cache writes."""
    for name, value in (("workers", workers), ("memory_budget_mb", memory_budget_mb),
                        ("worker_memory_mb", worker_memory_mb)):
        if type(value) is not int or value < 1:
            raise ValueError(name + " must be a positive integer")
    if memory_budget_mb < worker_memory_mb:
        raise ValueError("memory_budget_mb cannot accommodate one estimated worker")
    for name, value in (("stop_after", stop_after), ("decoded_bytes", decoded_bytes)):
        if value is None and name == "stop_after":
            continue
        if type(value) is not int or value < 0:
            raise ValueError(name + " must be a nonnegative integer")


def run_workflow(recipe=None, *, bundle=None, cache_root=None, workers=1,
                 memory_budget_mb=1024, worker_memory_mb=512,
                 stop_after=None, resume=None, supplied_parent=None,
                 decoded_bytes=DEFAULT_DECODED_BYTES):
    """Return exact R11 science plus separate truthful R12 execution accounting.

    Cache roots are explicit dedicated local paths. Without a cache, restart
    retains the original semantic replay. No performance claim follows merely
    from setting workers. Scientific UNKNOWN/production/canon gates are untouched.
    """
    started = time.perf_counter()
    validate_options(workers=workers, memory_budget_mb=memory_budget_mb,
                     worker_memory_mb=worker_memory_mb, stop_after=stop_after,
                     decoded_bytes=decoded_bytes)
    for name, value in (("recipe", recipe), ("supplied_parent", supplied_parent), ("resume", resume)):
        if value is not None and type(value) is not dict:
            raise ValueError(name + " must be an object")
    bundle = provenance.load_science() if bundle is None else bundle
    if bundle.source_sha256 != provenance.SCIENCE_SHA:
        raise ValueError('sealed R11 science required')
    identity = provenance.execution_identity(bundle)
    provenance.verify_execution(bundle, identity)
    storage = bundle.storage
    recipe = bundle.reference.recipe(bundle) if recipe is None else storage.decoded(storage.encoded(recipe))
    parent = None if supplied_parent is None else storage.decoded(storage.encoded(supplied_parent))
    checkpoint = None if resume is None else storage.decoded(storage.encoded(resume))
    built = assemble(bundle, recipe, supplied_parent=parent, decoded_bytes=decoded_bytes)
    stats = {}
    cache = None if cache_root is None else Store(Path(cache_root), provenance.sha(identity))
    pool = None
    if workers > 1:
        pool = PoolBackend(worker_run, initializer=worker_init,
                           initargs=(recipe, parent, identity, decoded_bytes,
                                     None if cache_root is None else str(Path(cache_root))), workers=workers,
                           memory_budget_mb=memory_budget_mb, worker_memory_mb=worker_memory_mb)

    def graph_run(graph_recipe, registry, **options):
        return executor.run(bundle.module('snapshot'), graph_recipe, registry, store=cache,
                            backend=None if pool is None else ArtifactBackend(pool, built),
                            on_computed=lambda ident, row: collect(built, ident, row),
                            on_restore=lambda ident, entry: restore(built, ident, entry),
                            stats=stats, **options)

    workflow = bundle.module('workflow')
    run = adapted(workflow.run, assemble=lambda *args, **kwargs: built,
                  s=SnapshotAdapter(bundle.module('snapshot'), graph_run))
    parent_stats = {}
    try:
        if pool is not None:
            pool.__enter__()
        with parents.reuse(bundle, cache, parent_stats):
            scientific = run(bundle, recipe, stop_after=stop_after, resume=checkpoint, supplied_parent=parent)
    finally:
        if pool is not None:
            pool.__exit__(None, None, None)
    provenance.verify_execution(bundle, identity)
    cache_stats = None if cache is None else deepcopy(cache.stats)
    execution = {'schema': 'diadem.shared-execution-receipt.r12', 'identity': identity,
                 'identity_sha256': provenance.sha(identity), 'stages': stats,
                 'cache': cache_stats, 'cache_warnings': cache_warnings(cache_stats),
                 'cache_statistics_scope': 'COORDINATOR_STORE_INSTANCE_ONLY; worker parent-cache operations are not included',
                 'decoded_artifacts': deepcopy(built['artifacts'].decode_stats),
                 'parent_runs_in_coordinator': parent_stats,
                 'parent_worker_reuse_accounting': 'NOT_COLLECTED' if pool is not None else 'NOT_APPLICABLE',
                 'requested_workers': workers, 'effective_workers': 1 if pool is None else pool.effective_workers,
                 'worker_pids': [] if pool is None else sorted(pool.observed_pids),
                 'worker_timings': [] if pool is None else deepcopy(pool.timings),
                 'elapsed_wall_seconds': time.perf_counter() - started,
                 'reference_scientific_metadata_retained_exactly': True,
                 'execution_policy': 'R12 reuse/parallelism; original R11 scientific scope text is unchanged',
                 'production_authorised': False, 'canon_changed': False}
    return {'scientific': scientific, 'execution': execution}
