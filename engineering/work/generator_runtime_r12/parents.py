"""Verified reuse at unchanged upstream recipe boundaries, not new science.

R11's graph snapshot identity intentionally changes with the entire recipe.
Caching sealed parent invocations separately lets a downstream-only parameter
edit reuse its identical R8/R9/R10 inputs without weakening graph identity.
The private bundle instances are restored on exit; source/module globals never
change. Only complete, non-resumed calls are eligible.
"""
from contextlib import contextmanager
from copy import deepcopy

from . import provenance


@contextmanager
def reuse(bundle, store, stats):
    stats.setdefault('executed', [])
    stats.setdefault('reused', [])
    if store is None:
        stats['accounting'] = 'NOT_COLLECTED_UNCACHED_REFERENCE'
        yield
        return
    stats['accounting'] = 'COMPLETE_FULL_PARENT_CALLS_ONLY; resumed/stopped calls bypass cache'
    saved = []
    # Resolve the entire sealed chain before changing any instance method.
    # An incomplete/malformed bundle must not leave a partially wrapped parent.
    targets = []
    parent = bundle.parent
    for version in (10, 9, 8):
        vars(parent)
        if not callable(parent.run) or not callable(parent.verify):
            raise ValueError('source-bound parent methods required')
        parent.storage
        parent.source_sha256
        targets.append((version, parent))
        parent = parent.parent
    for version, target in targets:
        original = target.run
        had_instance = 'run' in vars(target)
        previous_instance = vars(target).get('run')

        def make(target, original, version):
            def run(recipe, *, stop_after=None, resume=None):
                if stop_after is not None or resume is not None:
                    return original(recipe, stop_after=stop_after, resume=resume)
                target.verify()
                clean = target.storage.decoded(target.storage.encoded(recipe))
                recipe_sha = provenance.sha(clean)
                request = {'schema': 'diadem.verified-parent-invocation.r12',
                           'version': version, 'source_sha256': target.source_sha256,
                           'recipe_sha256': recipe_sha, 'stop_after': None, 'resume': None}
                key = provenance.sha(request)
                entry = store.get(key)
                if entry is None:
                    result = original(clean)
                    kind = 'executed'
                else:
                    if set(entry) != {'request', 'result'} or entry['request'] != request:
                        raise ValueError('cached parent invocation differs')
                    result = entry['result']
                    kind = 'reused'
                expected_schema = {8: 'diadem.biomes-vegetation-result.r8',
                                   9: 'diadem.species-spatial-result.r9',
                                   10: 'diadem.seasonal-world-result.r10'}[version]
                if (type(result) is not dict or result.get('schema') != expected_schema
                        or result.get('source_sha256') != target.source_sha256
                        or result.get('recipe_sha256') != recipe_sha):
                    raise ValueError('cached/computed parent scientific binding differs')
                target.verify()
                if kind == 'executed':
                    store.put(key, {'request': request, 'result': result})
                stats[kind].append({'version': version, 'invocation_sha256': key})
                return deepcopy(result)
            return run

        target.run = make(target, original, version)
        saved.append((target, had_instance, previous_instance))
    try:
        yield
    finally:
        for target, had_instance, previous_instance in reversed(saved):
            if had_instance:
                target.run = previous_instance
            else:
                del target.run
