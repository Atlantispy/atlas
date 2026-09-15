"""Private adapters for native R22 inner caches; scientific code stays intact.

Each copied function retains its native code object. Only its private globals
receive source verification and cache adapters; no imported module is patched.
Native ASCII-escaped provenance hashes remain native. The R24 Store supplies
the bounded fast storage encoder and separately binds every adapter source.
"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType, ModuleType, SimpleNamespace

from work.generator_upgrade_r20 import cache as native_cache
from work.generator_upgrade_r22 import registry as native, provenance as native_p
from work.generator_runtime_r12 import store as native_store


def _function(function, namespace):
    result = FunctionType(function.__code__, namespace, function.__name__,
                          function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    result.__annotations__ = function.__annotations__
    result.__qualname__ = function.__qualname__
    result.__doc__ = function.__doc__
    return result


def _module(original, **overrides):
    """Copy module-owned functions together, preserving private recursion."""
    result = ModuleType(original.__name__)
    result.__dict__.update(original.__dict__)
    for name, value in original.__dict__.items():
        if isinstance(value, FunctionType) and value.__globals__ is original.__dict__:
            result.__dict__[name] = _function(value, result.__dict__)
    result.__dict__.update(overrides)
    return result


class _Provenance:
    def __init__(self, original, expected, check):
        self._original, self._expected, self._check = original, deepcopy(expected), check

    def __getattr__(self, name):
        return getattr(self._original, name)

    def identity(self, **options):
        if options and (set(options) != {'moving_ground'}
                        or bool(options['moving_ground']) != (self._expected.get('moving_ground') is not None)):
            raise ValueError('private native provenance scope differs')
        self._check()
        return deepcopy(self._expected)

    def verify(self, expected):
        self._check()
        if expected != self._expected:
            raise ValueError('private native source/runtime binding differs; no repin')


class Adapter:
    """One source-bound operation, reusable across independently supplied inputs.

The optional verifier must check the complete supplied native binding freshly;
R24 adapter files are additionally verified at every original cache boundary.
"""
    def __init__(self, operation, *, binding=None, verify=None, adapter_sources=None):
        from . import provenance, verification
        from .storage import Store
        if operation not in native.OPERATIONS:
            raise ValueError('unknown R24 inner operation')
        self.operation = operation
        self.binding = deepcopy(verification.native_binding(operation) if binding is None else binding)
        self.adapter_sources = deepcopy(provenance.sources() if adapter_sources is None else adapter_sources)
        if type(self.adapter_sources) is not dict or not self.adapter_sources:
            raise ValueError('complete R24 inner source binding required')
        self._native_check = (lambda: verification.verify_native(operation, self.binding)) if verify is None else verify
        if not callable(self._native_check):
            raise ValueError('fresh native source verifier required')
        self._adapter_check = lambda: provenance.verify(self.adapter_sources)
        self._store_type = Store
        self._modules = {}
        self._check()
        self.StageCache = self._stage_cache()
        self.BoundStore = self._bound_store()

    def _check(self):
        self._native_check()
        self._adapter_check()

    def _stage_cache(self):
        outer = self
        identity = self.binding['r22'] if self.operation.startswith('terrain_') else self.binding
        political = identity['agriculture_soil_runtime']['storage_runtime']
        provenance = _Provenance(native_cache.p, political, self._check)
        store = SimpleNamespace(**{name: getattr(native_store, name)
            for name in ('_check_json', 'CacheError', 'CacheConflictError')}, Store=self._store_type)
        implementation = deepcopy(self.adapter_sources)
        implementation.update(political['sources'])
        private = dict(native_cache.__dict__, p=provenance, store=store,
                       _implementation=lambda: deepcopy(implementation))

        class StageCache(native_cache.StageCache):
            def __init__(self, name, binding, root=None, *, moving_ground=False):
                if moving_ground != (identity['moving_ground'] is not None):
                    raise ValueError('private stage-cache source scope differs')
                actual_root = Path(__file__).resolve().parents[2]/'c24' if root is None else Path(root)
                initialise(self, 'r22-'+name, {'execution': identity, 'binding': binding,
                    'r24_inner_sources': outer.adapter_sources}, actual_root)

            _verify = _function(native_cache.StageCache._verify, private)
            reuse = _function(native_cache.StageCache.reuse, private)

        initialise = _function(native_cache.StageCache.__init__, private)
        return StageCache

    def _bound_store(self):
        outer = self

        class BoundStore:
            """Exact native-facing type, with a distinct actual R24 namespace."""
            def __init__(self, root, namespace):
                outer._check()
                self.namespace = namespace
                self._store = outer._store_type(root, native_p.sha({
                    'native_namespace': namespace, 'r24_inner_sources': outer.adapter_sources}))

            def get(self, key):
                outer._check()
                result = self._store.get(key)
                outer._check()
                return result

            def put(self, key, value):
                outer._check()
                result = self._store.put(key, value)
                outer._check()
                return result

            @property
            def stats(self):
                return self._store.stats

        return BoundStore

    def _ordinary(self):
        if self.operation == 'crop_soil':
            from work.generator_upgrade_r22 import crop_development as original
            private = _module(original)
            builtins = original.__dict__['__builtins__']
            builtins = dict(builtins if isinstance(builtins, dict) else vars(builtins))
            original_import = builtins['__import__']
            stage_cache = self.StageCache

            def local_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'cache' and level == 1 and tuple(fromlist) == ('StageCache',):
                    return SimpleNamespace(StageCache=stage_cache)
                return original_import(name, globals, locals, fromlist, level)

            # Functions capture __builtins__ on construction, so rebuild them.
            private.__dict__['__builtins__'] = dict(builtins, __import__=local_import)
            for name, value in original.__dict__.items():
                if isinstance(value, FunctionType) and value.__globals__ is original.__dict__:
                    private.__dict__[name] = _function(value, private.__dict__)
            return private.run
        from work.generator_upgrade_r22 import placement
        private = _module(placement, StageCache=self.StageCache)
        return {'population_reference': private.assign_reference,
                'population_scenario': private.place, 'human_service': private.connect_human}[self.operation]

    def _terrain(self):
        from work.generator_upgrade_r22 import terrain
        consumer = _module(terrain.consumer,
            p=_Provenance(terrain.consumer.p, self.binding['r18'], self._check))
        regional_identity = self.binding['r18']['regional']['construction']
        consumer.regional = _module(terrain.consumer.regional,
            p=_Provenance(terrain.consumer.regional.p, regional_identity, self._check))
        return _module(terrain, consumer=consumer, Store=self.BoundStore,
            p=_Provenance(native_p, self.binding['r22'], self._check))

    def invoke(self, arguments, *, cache=True, cache_root=None):
        self._check()
        args = deepcopy(arguments)
        root = (Path(__file__).resolve().parents[2]/'c24' if cache_root is None else Path(cache_root)).resolve()
        try:
            if self.operation in ('crop_soil', 'population_reference', 'population_scenario', 'human_service'):
                if 'ordinary' not in self._modules:
                    self._modules['ordinary'] = self._ordinary()
                return self._modules['ordinary'](**args, cache=cache, cache_root=root)
            if self.operation == 'moving_roots':
                from work.generator_upgrade_r22 import moving_roots, evaporation
                engine = args.pop('soil_engine')
                if engine not in ('R13', 'R22_EVAPORATION'):
                    raise ValueError('explicit supported soil engine required')
                if 'moving' not in self._modules:
                    self._modules['moving'] = _module(moving_roots, Store=self.BoundStore,
                        p=_Provenance(native_p, self.binding, self._check))
                store = self.BoundStore(root, native_p.sha(self.binding)) if cache else None
                result = self._modules['moving'].run(**args, store=store,
                    soil_backend=evaporation if engine == 'R22_EVAPORATION' else None)
                result['execution']['r24_inner_sources'] = deepcopy(self.adapter_sources)
                return result
            if self.operation.startswith('terrain_'):
                envelope = args.get('envelope')
                if isinstance(envelope, dict):
                    supplied = envelope.get('execution', {}).get('r24_inner_sources')
                    if supplied is not None and supplied != self.adapter_sources:
                        raise ValueError('terrain R24 inner source binding changed; no silent repin')
                if 'terrain' not in self._modules:
                    self._modules['terrain'] = self._terrain()
                terrain = self._modules['terrain']
                if self.operation == 'terrain_advance':
                    store = self.BoundStore(root, terrain.cache_namespace(args['envelope'])) if cache else None
                    result = terrain.advance(**args, store=store)
                else:
                    result = {'terrain_from_seed': terrain.from_seed, 'terrain_view': terrain.view}[self.operation](**args)
                if self.operation != 'terrain_view':
                    result['execution']['r24_inner_sources'] = deepcopy(self.adapter_sources)
                return result
            return native.invoke(self.operation, args, cache=cache, cache_root=root)
        finally:
            self._check()


def invoke(operation, arguments, *, cache=True, cache_root=None,
           binding=None, verify=None, adapter_sources=None):
    return Adapter(operation, binding=binding, verify=verify,
        adapter_sources=adapter_sources).invoke(arguments, cache=cache, cache_root=cache_root)
