"""Versioned exact geology producers with invocation-local prepared inputs."""
from work.generator_upgrade_r26 import physical as original
from work.generator_upgrade_r28.preflight import clone
from work.geology_r1 import working, model, consumer, provenance as native
from . import provenance as p

OPERATIONS = {name: original.OPERATIONS[name] for name in
              ('regional_geology', 'geological_columns', 'geological_incise', 'geological_terrain_step')}


class Adapter:
    prepare = clone(original.Adapter.prepare, working=working, consumer=consumer,
                    _regional_sources=working.validate_sources)
    validate_result = clone(original.Adapter.validate_result, consumer=consumer)

    def __init__(self, operation, cache=True, cache_root=None, shared=None):
        if operation not in OPERATIONS:
            raise ValueError('versioned geology operation required')
        self.operation = operation
        self.shared = {} if shared is None else shared
        self.binding = native.identity()
        self.adapter_sources = p.sources()
        self.source_signature = native.sha({'operation': operation, 'native': self.binding,
                                           'adapter': self.adapter_sources})

    def verify(self):
        native.verify(self.binding)
        p.verify(self.adapter_sources)
        prepared = self.shared.get('geology_r1_prepared')
        if prepared is not None:
            prepared.verify_sources()

    def run(self, inputs, incoming):
        self.prepare(inputs, incoming)
        if self.operation == 'regional_geology':
            if 'geology_r1_prepared' not in self.shared:
                self.shared['geology_r1_prepared'] = working.Prepared()
            result = self.shared['geology_r1_prepared'].build(inputs['supports'], inputs['alternative'])
        elif self.operation == 'geological_columns':
            result = model.build(**inputs)
        elif self.operation == 'geological_incise':
            result = consumer.incise(original._snapshot(inputs, incoming),
                                     inputs['forcing'], inputs['duration_years'])
        else:
            result = consumer.terrain_step(original._snapshot(inputs, incoming), inputs['forcing'])
        return original.scientific(result)
