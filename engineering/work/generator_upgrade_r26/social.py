"""Private R19/R20/R21 adapters, preserving their complete scientific runners.

Inputs are explicit native JSON arguments. Dependencies supply disjoint argument
names; a name may never be silently overwritten. Coast time steps and shared
irrigation remain sequential; independent complete invocations use the parent
runner's bounded workers. No native module or retained launcher is patched.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import FunctionType, ModuleType, SimpleNamespace

from work.generator_runtime_r12 import store as original_store
from work.generator_upgrade_r24 import provenance as adapter_p
from work.generator_upgrade_r24.inner import _function, _module
from work.generator_upgrade_r24.storage import Store
from work.generator_upgrade_r24.verification import Reader

OPERATIONS = {
    'coastal_build_case': ('seas_coastal_processes',),
    'coastal_case': ('seas_coastal_processes',),
    'coastal_advance': ('seas_coastal_processes',),
    'political_districts': ('political_borders',),
    'agriculture': ('land_use_agriculture',),
}


class _Clones:
    """Fresh-reader native provenance; code objects and guard semantics unchanged."""
    def __init__(self, reader):
        self.reader, self.modules = reader, {}

    def module(self, source):
        if source.__name__ in self.modules:
            return self.modules[source.__name__]
        result = SimpleNamespace(**vars(source))
        self.modules[source.__name__] = result
        namespace = dict(vars(source))
        for name, value in tuple(namespace.items()):
            if isinstance(value, ModuleType) and value.__name__.endswith('.provenance'):
                namespace[name] = self.module(value)
        namespace['checked'] = self.reader.checked
        for name in ('identity', 'verify', 'execution_identity', 'verify_execution'):
            value = namespace.get(name)
            if isinstance(value, FunctionType):
                namespace[name] = _function(value, namespace)
        result.__dict__.update(namespace)
        return result


def _native_identity(module, expected=None):
    reader = Reader()
    try:
        private = _Clones(reader).module(module)
        if expected is not None:
            private.verify(expected)
        return private.identity()
    finally:
        reader.finish()


class _Provenance:
    def __init__(self, original, expected, check):
        self.original, self.expected, self.check = original, deepcopy(expected), check

    def __getattr__(self, name):
        return getattr(self.original, name)

    def identity(self):
        self.check()
        return deepcopy(self.expected)

    def verify(self, expected):
        self.check()
        if expected != self.expected:
            raise ValueError('native social source binding differs; no repin')


def _arguments(inputs, incoming):
    if type(inputs) is not dict or type(incoming) is not dict or set(inputs) & set(incoming):
        raise ValueError('explicit disjoint native arguments and dependencies required')
    result = deepcopy(dict(inputs, **incoming))
    original_store._check_json(result)
    return result


def _fields(arguments, required, optional=()):
    if not set(required) <= set(arguments) or set(arguments)-set(required)-set(optional):
        raise ValueError('exact native social operation arguments required')


def _stable(result):
    """Only run reporting/timing is separate; scientific content stays exact."""
    return {key: deepcopy(value) for key, value in result.items()
            if key not in ('reporting', 'elapsed_seconds')}


class Adapter:
    def __init__(self, operation, cache=True, cache_root=None, shared=None):
        if operation not in OPERATIONS:
            raise ValueError('unknown social operation')
        self.operation, self.cache = operation, cache
        self.root = (Path(__file__).resolve().parents[2]/'c26' if cache_root is None
                     else Path(cache_root)).resolve()
        if operation.startswith('coastal_'):
            from work.generator_upgrade_r19 import provenance, owner
        elif operation == 'political_districts':
            from work.generator_upgrade_r20 import provenance, owner
        else:
            from work.generator_upgrade_r21 import provenance, owner
        self.p, self.owner = provenance, owner
        self.native = _native_identity(self.p)
        self.owners = self._owners()
        self.sources = adapter_p.sources()
        self.own_path = Path(__file__).resolve()
        self.own_sha = hashlib.sha256(adapter_p.checked(self.own_path)).hexdigest()
        if globals().get('_R12_EXECUTED_SHA256') != self.own_sha:
            raise ValueError('social adapter executed source differs')
        self.source_signature = self.p.sha({'operation': operation, 'native': self.native,
            'owners': self.owners, 'r24_sources': self.sources,
            'r26_social': {str(self.own_path): self.own_sha}})
        self.last_diagnostics = {}
        self._private = None
        self.verify()

    def _owners(self):
        return (self.owner.binding(verify_sources=True) if self.operation == 'political_districts'
                else self.owner.binding())

    def _check_sources(self):
        # One fresh byte-reader per original source boundary. Sharing reads
        # within this pass does not retain stale content across boundaries.
        reader = Reader()
        try:
            _Clones(reader).module(self.p).verify(self.native)
            if (_module(adapter_p, checked=reader.checked).sources() != self.sources
                    or hashlib.sha256(reader.checked(self.own_path)).hexdigest() != self.own_sha
                    or globals().get('_R12_EXECUTED_SHA256') != self.own_sha):
                raise ValueError('social source/runtime binding changed; no repin')
        finally:
            reader.finish()

    def verify(self):
        self._check_sources()
        if self._owners() != self.owners:
            raise ValueError('social owner binding changed; no repin')

    def _stage_cache(self):
        from work.generator_upgrade_r20 import cache as source
        identity = self.native if self.operation == 'political_districts' else self.native['storage_runtime']
        implementation = dict(self.sources, **{str(self.own_path): self.own_sha})
        implementation.update(identity['sources'])
        proxy = SimpleNamespace(**vars(original_store))
        proxy.Store = Store
        namespace = dict(vars(source), p=_Provenance(source.p, identity, self._check_sources),
            store=proxy, _implementation=lambda: deepcopy(implementation))
        initialise = _function(source.StageCache.__init__, namespace)
        outer = self

        class StageCache(source.StageCache):
            def __init__(self, name, binding, root=None):
                initialise(self, name, {'native_binding': binding, 'r26_social': outer.source_signature},
                           outer.root if root is None else Path(root))

            _verify = _function(source.StageCache._verify, namespace)
            reuse = _function(source.StageCache.reuse, namespace)

        if self.operation == 'political_districts':
            return StageCache

        class AgricultureCache:
            def __init__(self, name, binding, root=None):
                outer._check_sources()
                self.cache = StageCache('r21-'+name, {'execution': outer.native, 'binding': binding}, root)

            def reuse(self, invocation, producer, validator):
                outer._check_sources()
                result = self.cache.reuse(invocation, producer, validator)
                outer._check_sources()
                return result

            @property
            def stats(self):
                return self.cache.stats

            @property
            def warnings(self):
                return self.cache.warnings

        return AgricultureCache

    def _coastal_cache(self):
        from work.generator_upgrade_r19 import cache as source
        outer = self
        proxy = SimpleNamespace(**vars(original_store))

        class BoundStore:
            def __init__(self, root, namespace):
                outer._check_sources()
                self._store = Store(outer.root if root is None else Path(root), source.p.sha({
                    'native_namespace': namespace, 'r26_social': outer.source_signature}))

            def get(self, key):
                return self._store.get(key)

            def put(self, key, value):
                return self._store.put(key, value)

            @property
            def stats(self):
                return self._store.stats

        proxy.Store = BoundStore
        namespace = dict(vars(source), store=proxy, DEFAULT_ROOT=self.root,
            p=_Provenance(source.p, self.native, self._check_sources))
        initialise = _function(source.CoastalCache.__init__, namespace)

        class CoastalCache(source.CoastalCache):
            def __init__(self, root=None, component='coastal'):
                initialise(self, outer.root if root is None else root, component)

        for name, method in source.CoastalCache.__dict__.items():
            if name != '__init__' and isinstance(method, FunctionType):
                setattr(CoastalCache, name, _function(method, namespace))
        return CoastalCache

    def _implementation(self):
        if self._private is not None:
            return self._private
        if self.operation == 'political_districts':
            from work.generator_upgrade_r20 import pipeline, hierarchy
            stage_cache = self._stage_cache()
            self._private = _module(pipeline, StageCache=stage_cache,
                hierarchy=_module(hierarchy, StageCache=stage_cache),
                p=_Provenance(pipeline.p, self.native, self._check_sources))
        elif self.operation == 'agriculture':
            from work.generator_upgrade_r21 import pipeline
            self._private = _module(pipeline, StageCache=self._stage_cache(),
                p=_Provenance(pipeline.p, self.native, self._check_sources))
        else:
            from work.generator_upgrade_r19 import working
            cache_class = self._coastal_cache()
            private = _module(working)
            builtins = working.__dict__['__builtins__']
            builtins = dict(builtins if isinstance(builtins, dict) else vars(builtins))
            native_import = builtins['__import__']

            def local_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'cache' and level == 1 and tuple(fromlist) == ('CoastalCache',):
                    return SimpleNamespace(CoastalCache=cache_class)
                return native_import(name, globals, locals, fromlist, level)

            private.__dict__['__builtins__'] = dict(builtins, __import__=local_import)
            for name, function in working.__dict__.items():
                if isinstance(function, FunctionType) and function.__globals__ is working.__dict__:
                    private.__dict__[name] = _function(function, private.__dict__)
            self._private = private
        return self._private

    def run(self, inputs, incoming):
        arguments = _arguments(inputs, incoming)
        self.verify()
        try:
            if self.operation == 'political_districts':
                _fields(arguments, ('physical', 'political'))
                # The separately supplied Stage2 document is exposed to the
                # native algorithm only after its immutable physical freeze.
                result = self._implementation().run(arguments['physical'],
                    lambda frozen: deepcopy(arguments['political']), cache=self.cache, cache_root=self.root)
            elif self.operation == 'agriculture':
                _fields(arguments, ('scenario',))
                result = self._implementation().run(arguments['scenario'], cache=self.cache, cache_root=self.root)
            elif self.operation == 'coastal_advance':
                _fields(arguments, ('checkpoint', 'end_s', 'forcing'), ('max_step_s', 'max_steps'))
                from work.generator_upgrade_r19.driver import CoastalRun
                checkpoint = arguments.pop('checkpoint')
                run = CoastalRun.restore(checkpoint)
                result = run.advance(**arguments)
            else:
                _fields(arguments, ('case_id',), () if self.operation == 'coastal_build_case'
                        else ('stop_s', 'max_step_s', 'phase_points'))
                private = self._implementation()
                run, evidence = private.build_case(arguments['case_id'], cache=self.cache)
                checkpoint = (run.checkpoint() if self.operation == 'coastal_build_case'
                    else private.run_case(run, cache=self.cache, **arguments))
                self.last_diagnostics = deepcopy(getattr(run, 'cache_reporting', {}))
                return {'checkpoint': checkpoint, 'evidence': evidence}
            self.last_diagnostics = deepcopy(result.get('reporting', {}))
            return _stable(result)
        finally:
            self.verify()

    def validate_result(self, result, inputs, incoming):
        """Outer cache hits retain input-file and native checkpoint safeguards."""
        arguments = _arguments(inputs, incoming)
        self.verify()
        if self.operation.startswith('coastal_'):
            from work.generator_upgrade_r19 import driver, working
            checkpoint = result if self.operation == 'coastal_advance' else result['checkpoint']
            run = driver.CoastalRun.restore(deepcopy(checkpoint))
            if self.operation == 'coastal_advance':
                if run.time != working.s.q(arguments['end_s']):
                    raise ValueError('coastal endpoint differs from requested input')
            else:
                evidence = result['evidence']
                if evidence['case_id'] != arguments['case_id']:
                    raise ValueError('coastal result case differs')
                snapshot = evidence['r18_snapshot']
                supports = {key: {name: row[name] for name in ('xy_m', 'area_m2')}
                    for key, row in snapshot['scientific']['supports'].items()}
                working._validate_geology(snapshot, supports)
                if self.owner.sources() != evidence['recovered_sources']:
                    raise ValueError('coastal recovered controls differ')
        elif result.get('scientific_sha256') != self.p.sha(result.get('scientific')):
            raise ValueError('social scientific result hash differs')
        self.verify()


def baseline(operation, inputs, *, cache=False, cache_root=None):
    """Unmodified native invocation, with the same deterministic output view."""
    arguments = _arguments(inputs, {})
    if operation == 'political_districts':
        from work.generator_upgrade_r20 import pipeline
        return _stable(pipeline.run(arguments['physical'], lambda frozen: deepcopy(arguments['political']),
            cache=cache, cache_root=cache_root))
    if operation == 'agriculture':
        from work.generator_upgrade_r21 import pipeline
        return _stable(pipeline.run(arguments['scenario'], cache=cache, cache_root=cache_root))
    if operation == 'coastal_advance':
        from work.generator_upgrade_r19.driver import CoastalRun
        return CoastalRun.restore(arguments.pop('checkpoint')).advance(**arguments)
    from work.generator_upgrade_r19 import working
    if cache_root is not None:
        raise ValueError('native R19 launcher has no cache-root argument; use cache=False for isolated baseline')
    run, evidence = working.build_case(arguments['case_id'], cache=cache)
    checkpoint = (run.checkpoint() if operation == 'coastal_build_case'
        else working.run_case(run, cache=cache, **arguments))
    return {'checkpoint': checkpoint, 'evidence': evidence}


def fixtures():
    """Small actual native mechanisms; no whole coast, map, or crop year."""
    from work.generator_upgrade_r20 import reference as political
    from work.generator_upgrade_r21 import reference as agriculture
    from work.generator_upgrade_r19 import driver, state
    from work.generator_upgrade_r18 import composite
    from work.generator_upgrade_r16 import regional
    from fractions import Fraction as F
    descriptor = composite.create([
        {'unit_id': 'R26-TEST', 'bulk_weight': '1', 'grain_density_kg_m3': '2000', 'porosity': '2/5'}],
        '1/100000', phase='mobile_sediment', evidence='SYNTHETIC TEST; finite coastal column')
    mid = descriptor['material_id']; palette = {mid: descriptor}
    _, native = regional.p.backend()
    def cell(water):
        layer = native.Layer(mid, F(1200), F(2000), F(2, 5), 'mobile_sediment', 'SYNTHETIC TEST')
        column = native.Column(F(1), F(-1), (layer,), 'SYNTHETIC TEST')
        return state.Cell(column, [F(0)], F(water), {}, (0., 0.), 'reach')
    run = driver.CoastalRun({'L': cell(2), 'R': cell(1)}, palette, [],
        [{'id': 'mouth', 'left': 'L', 'right': 'R', 'crest_m': '0', 'conductance_m2_s': '1'}],
        evidence='SYNTHETIC TEST; tiny finite reversible mouth', lineage={'fixture': 'R26_TWO_REACHES'})
    return {'political_districts': {'physical': political.physical(), 'political': political.political()},
        'agriculture': {'scenario': agriculture.scenario()},
        'coastal_advance': {'checkpoint': run.checkpoint(), 'end_s': '1/100', 'max_step_s': '1/100',
            'max_steps': 16, 'forcing': {'wind_stress_Pa': [0., 0.], 'wave_rms_shear_Pa': 0,
                'wave_direction_xy': [1., 0.], 'phase_points': 16}}}
