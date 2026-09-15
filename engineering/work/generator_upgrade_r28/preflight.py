"""Share one full parse between planning and execution in ONE invocation.

Not a validation cache: no file check, recipe or prepared graph survives a run.
The first call uses the complete original parser, including every producer's
source verifier, before worker startup. Only its exact, immediate consumer can
reuse that result. All execution/cache/result/final source guards remain native.
"""
from types import FunctionType


def clone(function, **overrides):
    result = FunctionType(function.__code__, dict(function.__globals__, **overrides),
        function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = None if function.__kwdefaults__ is None else function.__kwdefaults__.copy()
    return result


class _InvocationSnapshot:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self._calls = 0
        self._raw = self._registry = self._bindings = self._order = None
        # R24's no-cache checkpoint path invokes native snapshot.run, whose
        # global parse must also use this private one-shot boundary.
        self.run = clone(snapshot.run, parse=self.parse)

    def __getattr__(self, name):
        return getattr(self._snapshot, name)

    @staticmethod
    def _registration_bindings(registry):
        # Keep strong callable references, not only recyclable id() numbers.
        return {name:(tuple(sorted(row)), row['sha256'], row['run'], row['verify'])
            for name,row in registry.items()}

    def _matches(self, registry):
        if registry is not self._registry or set(registry) != set(self._bindings):
            return False
        for name, (fields, signature, run, verify) in self._bindings.items():
            row = registry[name]
            if (type(row) is not dict or tuple(sorted(row)) != fields
                    or row.get('sha256') != signature or row.get('run') is not run
                    or row.get('verify') is not verify):
                return False
        return True

    def parse(self, recipe, registry):
        self._calls += 1
        if self._calls == 1:
            raw = self._snapshot.encoded(recipe)
            self._registry = registry
            self._bindings = self._registration_bindings(registry)
            nodes, order = self._snapshot.parse(recipe, registry)
            if self._snapshot.encoded(recipe) != raw or not self._matches(registry):
                raise ValueError('recipe or registration changed during authoritative preflight')
            self._raw = raw
            self._order = tuple(order)
            return nodes, order
        if self._calls != 2 or self._raw is None:
            raise ValueError('preflight is invocation-local and single-use')
        if self._snapshot.encoded(recipe) != self._raw or not self._matches(registry):
            raise ValueError('recipe or registration changed after authoritative preflight')
        # The executor made its own detached copy. Return its stage objects,
        # never mutable nodes retained from the scheduling recipe.
        return {stage['stage_id']:stage for stage in recipe['stages']}, list(self._order)

    @property
    def diagnostics(self):
        return {'authoritative_parse_passes': min(self._calls,1),
            'duplicate_parse_passes_avoided': int(self._calls == 2),
            'reuse_scope':'SAME_INVOCATION_EXACT_RECIPE_AND_REGISTRATIONS',
            'persistent_validation_cache':False,
            'execution_cache_result_and_final_source_guards':'UNCHANGED'}
