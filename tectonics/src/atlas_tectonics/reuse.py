"""Optional persistent reuse for known pure kernels, never inside their equations.

Inputs are detached before hashing and use. Identity includes typed input bytes,
resolved parameters, current package source, loaded Python instructions and the
selected runtime. This is provenance/invalidation, not a hostile-runtime sandbox.
No parameter-only hash is treated as a complete scientific result identity.
"""
from __future__ import annotations
from dataclasses import asdict
from functools import lru_cache
import hashlib
import inspect
import json
import marshal
import math
from pathlib import Path
import platform
import sys
import types

import numpy as np

from ._validation import array, input_shape, TectonicsError
from .resources import elements, select_budget
from .storage import ArrayStore
from .thermal import half_space_temperature
from .flexure import PeriodicFlexure
from .parameters import ThermalParameters


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _file_hash(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise TectonicsError('runtime/source file unavailable or linked')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=16)
def _loaded_binary(path):
    # Binary modules are assumed immutable for a process lifetime. Python source
    # and loaded instructions are re-examined per invocation. Paths are not IDs.
    return _file_hash(path)


def _normal_code(code):
    return code.replace(co_filename='<atlas>', co_consts=tuple(
        _normal_code(c) if isinstance(c, types.CodeType) else c for c in code.co_consts))


def execution_identity(backend='reference'):
    if backend not in ('reference', 'scipy'):
        raise TectonicsError('unknown execution backend')
    root = Path(__file__).parent
    sources = {p.name: _file_hash(p) for p in sorted(root.glob('*.py'))}
    loaded = {}
    for module_name, module in sorted(tuple(sys.modules.items())):
        if module_name != 'atlas_tectonics' and not module_name.startswith('atlas_tectonics.'):
            continue
        for name, obj in sorted(vars(module).items()):
            funcs = [(name, obj)]
            if isinstance(obj, type) and obj.__module__ == module_name:
                funcs = []
                for member, method in sorted(vars(obj).items()):
                    if isinstance(method, (staticmethod, classmethod)):
                        method = method.__func__
                    elif isinstance(method, property):
                        method = method.fget
                    funcs.append((name + '.' + member, method))
            for label, fn in funcs:
                if inspect.isfunction(fn) and fn.__module__ == module_name:
                    loaded[module_name + '.' + label] = _digest(marshal.dumps(_normal_code(fn.__code__)))
    import numpy._core._multiarray_umath as core
    import numpy.fft._pocketfft_umath as fft
    binaries = {'python': _loaded_binary(sys.executable),
                'numpy_core': _loaded_binary(core.__file__),
                'numpy_fft': _loaded_binary(fft.__file__),
                'math': _loaded_binary(getattr(math, '__file__', sys.executable))}
    versions = {'python': sys.version, 'numpy': np.__version__, 'machine': platform.machine(),
                'platform': platform.system(), 'byteorder': sys.byteorder}
    if backend == 'scipy':
        try:
            import scipy
            import scipy.special._ufuncs as sf
        except ImportError as exc:
            raise TectonicsError('requested scipy runtime unavailable') from exc
        versions['scipy'] = scipy.__version__
        binaries['scipy_special'] = _loaded_binary(sf.__file__)
    return _digest(_json({'schema': 'atlas.kernel-execution.v1', 'backend': backend,
                         'sources': sources, 'loaded_code': loaded,
                         'runtime': versions, 'binaries': binaries}))


def _array_identity(a):
    h = hashlib.sha256(_json({'dtype': a.dtype.str, 'shape': a.shape}))
    view = memoryview(a).cast('B')
    for offset in range(0, len(view), 1024 * 1024):
        h.update(view[offset:offset+1024*1024])
    return h.hexdigest()


def _invocation_record(operation, inputs, parameters, backend):
    return {'schema': 'atlas.kernel-invocation.v1', 'operation': operation,
        'backend': backend, 'execution': execution_identity(backend),
        'inputs': {k: {'identity': _array_identity(v), 'shape': list(v.shape),
                       'dtype': v.dtype.str} for k, v in sorted(inputs.items())},
        'parameters': parameters}


def invocation_identity(operation, inputs, parameters, *, backend='reference'):
    return _digest(_json(_invocation_record(operation, inputs, parameters, backend)))


def _evaluate(store, record, compute, shape, budget):
    if not isinstance(store, ArrayStore):
        raise TectonicsError('store must be an ArrayStore')
    key = _digest(_json(record))
    restored = store.get(key, budget=budget)
    if restored is not None:
        if (set(restored) != {'result'} or restored['result'].shape != shape
                or restored['result'].dtype != np.dtype('float64')
                or store.metadata(key) != record):
            raise TectonicsError('cached result contract mismatch')
        result = restored['result']
    else:
        result = compute()
    if execution_identity(record['backend']) != record['execution']:
        raise TectonicsError('implementation changed during invocation; result not published')
    if restored is None:
        store.put(key, {'result': result}, record)
    return result


def cached_temperature(depth_m, age_s, parameters: ThermalParameters, *,
                       store: ArrayStore | None = None, backend='reference', budget=None):
    """Same units/boundaries as half_space_temperature; caching is optional."""
    if store is None:
        return half_space_temperature(depth_m, age_s, parameters, backend=backend, budget=budget)
    ds, ts = input_shape(depth_m), input_shape(age_s)
    bs = np.broadcast_shapes(ds, ts)
    policy = select_budget(budget)
    with policy.reserve(8 * (elements(ds) + elements(ts))):
        depth = array(depth_m, 'depth', nonnegative=True)
        age = array(age_s, 'age', nonnegative=True)
        if not isinstance(parameters, ThermalParameters):
            raise TectonicsError('explicit ThermalParameters required')
        # Refuse projected output even on a cache hit; restored data are not free.
        with policy.reserve(128 * elements(bs)):
            record = _invocation_record('half-space-temperature-v2', {'depth': depth, 'age': age},
                                        asdict(parameters), backend)
        return _evaluate(store, record, lambda: half_space_temperature(
            depth, age, parameters, backend=backend, budget=policy), bs, policy)


def cached_flexure(operator: PeriodicFlexure, load_pa, *, store: ArrayStore | None = None, budget=None):
    if not isinstance(operator, PeriodicFlexure):
        raise TectonicsError('explicit PeriodicFlexure required')
    if store is None:
        return operator.solve(load_pa, budget=budget)
    shape = input_shape(load_pa)
    if not shape or shape[-1] != operator.grid.cells:
        raise TectonicsError('load final dimension must equal grid cells')
    policy = select_budget(budget)
    with policy.reserve(8 * elements(shape)):
        load = array(load_pa, 'load')
        with policy.reserve(128 * elements(shape)):
            record = _invocation_record('periodic-flexure-v2', {'load': load},
                {'grid': asdict(operator.grid), 'material': asdict(operator.parameters),
                 'operator_id': operator.operator_id}, 'reference')
        return _evaluate(store, record, lambda: operator.solve(load, budget=policy), shape, policy)
