"""Release-policy check scenarios: one process per scenario, the result as one JSON line on stdout.

usage: scenario.py SCENARIO WORKDIR

Run twice per scenario by test_release_payload: in strict (the composition's own src on PYTHONPATH) and as an
allow-listed tools entry of a disposable packaged payload (release). The payload is a test fixture of the mode
machinery only; no evidence is produced in it, and parity of a real packaged build is a separate, later check.
"""
import hashlib
import json
import sys
import traceback
from pathlib import Path


def _error(exc):
    return '%s: %s' % (type(exc).__name__, exc)


def mode(_):
    from atlas_tectonics.reuse import execution_mode
    return {'mode': execution_mode()}


def worker_entry(_):
    import atlas_tectonics
    # integration_parallel_worker.run_worker sets argv[0] to this path before runpy (decision 3).
    sys.argv[0] = str(Path(str(atlas_tectonics.__file__)).absolute().parent / 'integration_parallel_worker.py')
    from atlas_tectonics.reuse import execution_mode
    return {'mode': execution_mode()}


def evidence(_):
    from atlas_tectonics.reuse import execution_mode, require_strict_execution
    try:
        require_strict_execution()
        refused = None
    except Exception as exc:
        refused = _error(exc)
    return {'mode': execution_mode(), 'refused': refused}


def hold(_):
    """Release keeps the source hold after a context closes (decision 2); strict releases it."""
    import atlas_tectonics
    from atlas_tectonics.reuse import ExecutionContext, execution_mode
    source = Path(str(atlas_tectonics.__file__)).absolute().parent / 'parameters.py'
    context = ExecutionContext('reference')
    context.close()
    try:
        with open(source, 'r+b'):
            pass
        writable = True
    except PermissionError:
        writable = False
    again = ExecutionContext('reference')
    again.verify_boundary()
    identity = again.identity
    again.close()
    return {'mode': execution_mode(), 'writable_after_close': writable, 'identity': identity}


def drift(_):
    """A rebinding between boundaries refuses publication_boundary; restoring it passes again."""
    from atlas_tectonics import reuse
    out = {'mode': reuse.execution_mode()}
    with reuse.ExecutionContext('reference'):
        reuse.publication_boundary()
        saved = reuse.invocation_identity
        reuse.invocation_identity = lambda *args, **kwargs: None
        try:
            reuse.publication_boundary()
            out['drifted'] = None
        except Exception as exc:
            out['drifted'] = _error(exc)
        finally:
            reuse.invocation_identity = saved
        reuse.publication_boundary()
        out['restored'] = 'ok'
    return out


def race(_):
    """A context closed by its own thread between the boundary's snapshot and its check is skipped, not refused."""
    from atlas_tectonics import reuse
    out = {'mode': reuse.execution_mode()}
    context = reuse.ExecutionContext('reference')
    context.__enter__()

    def closing():
        del context.verify_boundary   # unpatched first: close() verifies through it
        context.close()   # the other thread's exit, landing between the snapshot and this check
        return context.verify_boundary()

    context.verify_boundary = closing
    try:
        reuse.publication_boundary()
        out['closed_meanwhile'] = 'skipped'
    except Exception as exc:
        out['closed_meanwhile'] = _error(exc)
    finally:
        context.__dict__.pop('verify_boundary', None)
        context.__exit__(None, None, None)
    return out


def seal(workdir):
    """B13 at the compact seal and at promotion: a drift refuses both; nothing is published while drifted."""
    import test_interval_store_set as T
    from atlas_tectonics import reuse
    from interval_store_set import IntervalStoreSet
    out = {'mode': reuse.execution_mode()}
    scope = T.scope()
    with reuse.ExecutionContext('reference'):
        stores = IntervalStoreSet.create_migration(str(Path(workdir) / 'catalog.json'), workflow_id=T.WORKFLOW,
                                                   scope=scope)
        saved = reuse.invocation_identity
        try:
            candidate, ref, _ = T.add_interval(stores, [b'abc' * 50])
            reuse.invocation_identity = lambda *args, **kwargs: None
            try:
                candidate.seal(ref)
                out['seal_drifted'] = None
            except Exception as exc:
                out['seal_drifted'] = _error(exc)
            reuse.invocation_identity = saved
            sealed = candidate.seal(ref)
            before = stores.catalog_digest
            reuse.invocation_identity = lambda *args, **kwargs: None
            try:
                stores.promote(sealed, expected_catalog_digest=before)
                out['promote_drifted'] = None
            except Exception as exc:
                out['promote_drifted'] = _error(exc)
            reuse.invocation_identity = saved
            out['catalog_unchanged_while_drifted'] = stores.catalog_digest == before
            entry = stores.promote(sealed, expected_catalog_digest=before)
            out['promoted_after_restore'] = entry.interval
        finally:
            reuse.invocation_identity = saved
            stores.close()
    scope.close()
    return out


def parity(workdir):
    """A matched small workload: cold compute + store, warm reuse, reuse after reopening the store."""
    import numpy as np

    from atlas_tectonics.parameters import ThermalParameters
    from atlas_tectonics.reuse import CachePolicy, ExecutionContext, cached_temperature, execution_mode
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    limits = StoreLimits(chunk_bytes=65536, max_array_bytes=64 << 20, max_store_bytes=256 << 20)
    parameters = ThermalParameters('release-parity', 'release parity check', 273.15, 1600.0, 1.0e-6)
    depth = np.linspace(0.0, 150.0e3, 257)[:, None]
    age = np.linspace(1.0e12, 3.0e15, 129)[None, :]
    policy = CachePolicy(mode='always', min_result_bytes=0, min_compute_seconds=0.0, expected_reuses=1)
    path = Path(workdir) / 'parity.sqlite'
    digests = []
    context = ExecutionContext('scipy')
    with ArrayStore(path, limits) as store:
        for _ in range(2):
            value = cached_temperature(depth, age, parameters, store=store, backend='scipy', context=context,
                                       cache_policy=policy)
            digests.append(hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
        first = store.statistics()
    with ArrayStore(path, limits) as store:
        value = cached_temperature(depth, age, parameters, store=store, backend='scipy', context=context,
                                   cache_policy=policy)
        digests.append(hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
        second = store.statistics()
    identity = context.identity
    context.close()
    return {'mode': execution_mode(), 'digests': digests, 'identity': identity,
            'statistics': [repr(first), repr(second)]}


SCENARIOS = {'mode': mode, 'worker-entry': worker_entry, 'evidence': evidence, 'hold': hold, 'drift': drift,
             'race': race, 'seal': seal, 'parity': parity}


def main():
    name, workdir = sys.argv[1], sys.argv[2]
    try:
        result = {'ok': True, **SCENARIOS[name](workdir)}
    except Exception as exc:
        result = {'ok': False, 'error': _error(exc), 'trace': traceback.format_exc()[-1500:]}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
