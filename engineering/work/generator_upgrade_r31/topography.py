"""Exact terrain kernels in current terrain, geology, routing and rooted ground.

New producer pins are mandatory. Old R22 envelopes require explicit native
import_r22 before use, not automatic adoption by the graph adapter.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from fractions import Fraction
from work.generator_upgrade_r24.inner import _module
from work.generator_upgrade_r28.preflight import clone
from work.generator_upgrade_r26 import physical
from work.generator_upgrade_r22 import moving_roots, evaporation
from work.generator_runtime_r12.store import Store
from work.geology_r1 import consumer
from work.topography_r1 import terrain, kernels, transport, provenance as native
from . import provenance as p

OPERATIONS = {
    'terrain_from_seed':('topography_topology',),
    'terrain_advance':('topography_topology','erosion_sediment_transport','hydrology'),
    'terrain_view':('topography_topology',),
    'moving_roots':('soils_ground_conditions','erosion_sediment_transport'),
    'geological_terrain_step':physical.OPERATIONS['geological_terrain_step'],
    'surface_water_route':physical.OPERATIONS['surface_water_route'],
}

_terrain_step = clone(consumer.terrain_step, terrain=kernels)


def _identity(operation):
    # These two stateless routes do not call R22 terrain/rooted soil. Retain
    # their exact previous native closure plus every new kernel/helper source,
    # rather than checking unrelated R22 ancestry at each cache/job boundary.
    if operation == 'surface_water_route':
        return {'schema':'diadem.scoped-topography-route.r31',
                'sources':native.sources(), 'ground':physical._identity(operation)}
    if operation == 'geological_terrain_step':
        return {'schema':'diadem.scoped-topography-geology.r31',
                'sources':native.sources(), 'geology':consumer.p.identity()}
    return native.identity()


class Adapter:
    def __init__(self, operation, cache=True, cache_root=None, shared=None):
        if operation not in OPERATIONS:
            raise ValueError('versioned topography operation required')
        self.operation, self.cache = operation, cache
        self.cache_root = Path(__file__).resolve().parents[2]/'c26' if cache_root is None else Path(cache_root)
        self.binding, self.adapter_sources = _identity(operation), p.sources()
        self.source_signature = native.sha({'operation':operation,'native':self.binding,
                                           'adapter':self.adapter_sources})
        self._moving = None

    def verify(self):
        if self.operation in ('surface_water_route','geological_terrain_step'):
            if _identity(self.operation) != self.binding:
                raise ValueError('scoped topography native source/runtime differs')
        else:
            native.verify(self.binding)
        p.verify(self.adapter_sources)

    def _moving_module(self):
        if self._moving is None:
            binding = {'schema':'diadem.rooted-ground-topography-binding.r31',
                       'native':self.binding,'adapter':self.adapter_sources}
            def identity(*, moving_ground=False):
                if moving_ground is not True:
                    raise ValueError('rooted ground source scope required')
                self.verify()
                return deepcopy(binding)
            def verify(expected):
                self.verify()
                if expected != binding:
                    raise ValueError('rooted ground topography source binding differs')
            provenance = SimpleNamespace(**dict(vars(moving_roots.p), identity=identity, verify=verify))
            self._moving = _module(moving_roots, transport=transport, p=provenance)
        return self._moving

    @staticmethod
    def _args(inputs, incoming):
        if set(inputs) & set(incoming):
            raise ValueError('dependency cannot overwrite explicit input')
        return deepcopy({**inputs, **incoming})

    def prepare(self, inputs, incoming):
        native.encoded(inputs); native.encoded(incoming)
        args = self._args(inputs, incoming)
        operation = self.operation
        if operation.startswith('terrain_'):
            fields = {'snapshot','clock'} if operation == 'terrain_from_seed' else {'envelope'}
            if operation == 'terrain_advance':
                fields.add('forcing')
            physical._exact(args, fields, operation)
        elif operation == 'moving_roots':
            fields = {'spec','soil_engine'} | (set(args) & {'stop_after','resume'})
            physical._exact(args, fields, operation)
            if args['soil_engine'] not in ('R13','R22_EVAPORATION'):
                raise ValueError('explicit supported soil engine required')
        elif operation == 'geological_terrain_step':
            fields = {'forcing'} | ({'snapshot'} if 'snapshot' in inputs else set())
            physical._exact(inputs, fields, operation)
            consumer.verify(physical._snapshot(inputs, incoming))
        else:
            physical._exact(inputs, ('state','local_runoff_m3','connectors','duration_years'), operation)
            if incoming:
                raise ValueError('surface routing requires its explicit current native state')
        return args

    def run(self, inputs, incoming):
        args = self.prepare(inputs, incoming)
        operation = self.operation
        if operation == 'terrain_from_seed':
            result = terrain.from_seed(**args)
        elif operation == 'terrain_advance':
            result = terrain.advance(**args, cache_root=self.cache_root if self.cache else None)
        elif operation == 'terrain_view':
            result = terrain.view(**args)
        elif operation == 'moving_roots':
            engine = args.pop('soil_engine')
            module = self._moving_module()
            store = Store(self.cache_root, native.sha(module.p.identity(moving_ground=True))) if self.cache else None
            result = module.run(**args, store=store,
                soil_backend=evaporation if engine == 'R22_EVAPORATION' else None)
            result.pop('execution', None)
        elif operation == 'geological_terrain_step':
            result = _terrain_step(physical._snapshot(inputs, incoming), inputs['forcing'])
        else:
            _, tt = consumer.regional.p.backend()
            connectors = []
            for item in args['connectors']:
                row = dict(item, length_m=physical._q(item['length_m']))
                if row['outlet_elevation_m'] is not None:
                    row['outlet_elevation_m'] = consumer.regional._signed(row['outlet_elevation_m'])
                connectors.append(tt.Connector(**row))
            result = kernels.route_water(tt.LandscapeState.from_dict(args['state']),
                {key:physical._q(value) for key,value in args['local_runoff_m3'].items()},
                tuple(connectors), duration_years=physical._q(args['duration_years']))
        if operation in ('terrain_from_seed','terrain_advance'):
            result['execution'] = {key:value for key,value in result['execution'].items()
                                   if key not in ('cache_hit','cache_key')}
        return physical.scientific(result)

    def _accepted_terrain(self, envelope):
        """Fresh readback at an already-authenticated executor callback only.

        This is not the public native verifier. R24 has just authenticated the
        entire invocation, producer, dependency and product. Retain envelope,
        source, external-owner and namespace guards here without interpreting
        every historical numerical balance a second time on a warm cache hit.
        Native production and public verify still perform the full validation.
        """
        physical._exact(envelope, ('schema','binding','body','body_sha256','execution'),
                        'authenticated terrain receipt')
        expected = {'topography_r1':self.binding,
                    'physical_decision':{'path':str(terrain.DECISION),'sha256':terrain.DECISION_SHA}}
        if (envelope['schema'] != terrain.SCHEMA or envelope['binding'] != expected
                or envelope['body_sha256'] != native.sha(envelope['body'])
                or envelope['execution']['cache_namespace'] != native.sha(expected)):
            raise ValueError('authenticated terrain envelope/source/namespace differs')
        terrain._decision()
        body = envelope['body']; seed = body['seed']; science = seed['scientific']
        if (body['seed_scientific_sha256'] != seed['execution']['scientific_sha256']
                or seed['execution']['scientific_sha256'] != native.sha(science)
                or body['selection']['decision_sha256'] != terrain.DECISION_SHA):
            raise ValueError('authenticated selected terrain seed differs')
        details = science['regional_input']
        if (details.get('alternative') != 'DEFAULT'
                or details.get('owner_input') != {'path':str(terrain.working.INPUT),'sha256':terrain.working.INPUT_SHA}
                or body['palette'] != details['palette']):
            raise ValueError('authenticated terrain selected input/palette differs')
        for source in (science['owner_source'], details['source_package'], details['owner_input']):
            consumer.regional._owner_source(source)
        return body

    def validate_result(self, result, inputs, incoming):
        args = self.prepare(inputs, incoming)
        native.encoded(result)
        if self.operation == 'terrain_from_seed':
            body = self._accepted_terrain(result)
            if body['seed'] != args['snapshot'] or body['clock'] != args['clock'] or body['history']:
                raise ValueError('authenticated terrain constructor input differs')
        elif self.operation == 'terrain_advance':
            body = self._accepted_terrain(result)
            parent = self._accepted_terrain(args['envelope'])
            forcing = args['forcing']
            if (len(body['history']) != len(parent['history'])+1
                    or body['history'][:-1] != parent['history']
                    or any(body[key] != parent[key] for key in
                           ('seed','seed_scientific_sha256','selection','clock','palette'))):
                raise ValueError('authenticated terrain history/seed predecessor differs')
            row = body['history'][-1]
            duration = consumer.columns._q(forcing['duration_years'],'terrain duration',positive=True)
            if (row['forcing'] != forcing or row['forcing_sha256'] != native.sha(forcing)
                    or row['row_sha256'] != native.sha({key:item for key,item in row.items() if key != 'row_sha256'})
                    or row['initial_state_sha256'] != native.sha(parent['current_state'])
                    or row['final_state_sha256'] != native.sha(body['current_state'])
                    or row['native_result']['r22_parent_state_sha256'] != native.sha(parent['current_state'])
                    or row['native_result']['r22_parent_envelope_sha256'] != args['envelope']['body_sha256']
                    or Fraction(body['elapsed_years']) != Fraction(parent['elapsed_years'])+duration
                    or Fraction(body['elapsed_seconds']) != Fraction(body['elapsed_years'])*Fraction(body['clock']['seconds_per_year'])):
                raise ValueError('authenticated terrain forcing/state/clock linkage differs')
        elif self.operation == 'terrain_view':
            envelope = args['envelope']
            body = self._accepted_terrain(envelope)
            digest = native.sha(envelope)
            def accepted(value):
                if value is not envelope or native.sha(value) != digest:
                    raise ValueError('private authenticated terrain view changed')
                return body
            if result != clone(terrain.view,verify=accepted)(envelope):
                raise ValueError('native current terrain view differs')
        elif self.operation == 'moving_roots':
            engine = args.pop('soil_engine')
            module = self._moving_module()
            backend = evaporation if engine == 'R22_EVAPORATION' else None
            module.validate(args['spec'], soil_backend=backend)
            science = result['scientific']
            if science['source_sha256'] != native.sha(module.p.identity(moving_ground=True)):
                raise ValueError('native rooted result source differs')
            for row in science['events']:
                module.audit_event(row, args['spec']['coupling_controls'], soil_backend=backend)
        elif self.operation == 'geological_terrain_step':
            if result.get('r18_input_scientific_sha256') != physical._snapshot(inputs, incoming)['execution']['scientific_sha256']:
                raise ValueError('native geological terrain parent identity differs')
        else:
            if sum(map(Fraction,result['local_runoff_m3'].values()),Fraction()) != sum(
                    map(Fraction,result['external_exports_m3'].values()),Fraction()):
                raise ValueError('native exact routed water conservation differs')
