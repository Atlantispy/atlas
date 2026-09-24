"""Public W12 producer wiring through the retained typed Atlas graph.

Only the standalone R11 graph contract, R24 executor and R12 authenticated store
are loaded. The physical preparation and its native data remain owned by the
supplied plan; the second operation inspects fields without changing physics.
"""
from copy import deepcopy
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
_ADAPTER_PATH = Path(__file__).resolve()
_ADAPTER_BYTES = _ADAPTER_PATH.read_bytes()
if sys._getframe().f_code != compile(_ADAPTER_BYTES, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed W12 graph adapter differs from current source')
_ADAPTER_EXECUTED_SHA256 = hashlib.sha256(_ADAPTER_BYTES).hexdigest()
del _ADAPTER_BYTES

PRODUCER = 'atlas_tectonics_column_assembly_v1'
INSPECTOR = 'atlas_tectonics_field_inspection_v1'


def _components():
    """Load public execution components, never the scientific registry stack."""
    engineering = str(ROOT/'engineering')
    inserted = engineering not in sys.path
    if inserted:
        sys.path.insert(0, engineering)
    try:
        runtime = importlib.import_module('work.generator_runtime_r12')
        retained = importlib.import_module('work.generator_upgrade_r24')
        executor = importlib.import_module('work.generator_upgrade_r24.executor')
        store = importlib.import_module('work.generator_runtime_r12.store')
    finally:
        if inserted:
            sys.path.remove(engineering)
    expected = {
        runtime: ROOT/'engineering/work/generator_runtime_r12/__init__.py',
        retained: ROOT/'engineering/work/generator_upgrade_r24/__init__.py',
        executor: ROOT/'engineering/work/generator_upgrade_r24/executor.py',
        store: ROOT/'engineering/work/generator_runtime_r12/store.py',
    }
    for module, path in expected.items():
        if Path(module.__file__).resolve() != path:
            raise ValueError('foreign public graph component: '+module.__name__)
    path = ROOT/'engineering/work/generator_upgrade_r11/snapshot.py'
    spec = importlib.util.spec_from_file_location('_atlas_w12_snapshot_v1', path,
                                                loader=runtime._CapturedLoader(path))
    if spec is None or spec.loader is None:
        raise ValueError('cannot load captured public graph contract')
    snapshot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(snapshot)
    expected[snapshot] = path
    return snapshot, executor, store.Store, runtime, expected


def _source_records(runtime, modules):
    """Bind executed bytes as well as fresh current bytes; never repin a module."""
    records = {}
    for module, path in modules.items():
        digest = hashlib.sha256(runtime._raw(path)).hexdigest()
        if getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
            raise ValueError('executed public graph component source differs: '+module.__name__)
        records[path.relative_to(ROOT).as_posix()] = digest
    digest = hashlib.sha256(runtime._raw(_ADAPTER_PATH)).hexdigest()
    if digest != _ADAPTER_EXECUTED_SHA256:
        raise ValueError('W12 graph adapter source changed; create a new invocation')
    records[_ADAPTER_PATH.relative_to(ROOT).as_posix()] = digest
    return records


class _Binding:
    def __init__(self, plan, snapshot, runtime, modules):
        for name in ('run', 'verify', 'verify_product', 'read_fields', 'statistics'):
            if not callable(getattr(plan, name, None)):
                raise ValueError('supported assembly plan method required: '+name)
        plan.verify()
        self.plan, self.snapshot = plan, snapshot
        self.runtime, self.modules = runtime, modules
        self.plan_id = snapshot.digest(plan.plan_id)
        self.context = deepcopy(snapshot.context(plan.context))
        self.sources = _source_records(runtime, modules)
        self.record = dict(schema='atlas.w12-public-graph-binding.v1',
            plan_id=self.plan_id, context=self.context, sources=self.sources,
            runtime=dict(python=sys.version, implementation=sys.implementation.name,
                         cache_tag=sys.implementation.cache_tag, platform=sys.platform,
                         byteorder=sys.byteorder))
        self.identity = snapshot.sha(self.record)

    def verify(self):
        self.plan.verify()
        if self.plan.plan_id != self.plan_id or self.plan.context != self.context:
            raise ValueError('assembly plan identity/context changed during graph invocation')
        if _source_records(self.runtime, self.modules) != self.sources:
            raise ValueError('public graph source changed; no silent rebind')


def _field_inventory(plan, product, snapshot):
    """Consume the actual immutable arrays, without constructing terrain."""
    plan.verify_product(product)
    fields = plan.read_fields(product)
    if type(fields) is not dict or not fields:
        raise ValueError('nonempty named immutable tectonics fields required')
    inventory = {}
    for name, array in sorted(fields.items()):
        snapshot.text(name)
        view = memoryview(array)
        dtype = getattr(array, 'dtype', None)
        if (not view.readonly or not view.c_contiguous or dtype is None
                or getattr(dtype, 'hasobject', True)):
            raise ValueError('immutable contiguous non-object tectonics array required')
        inventory[name] = dict(dtype=dtype.str, shape=list(view.shape),
            nbytes=view.nbytes, sha256=hashlib.sha256(view.cast('B')).hexdigest())
    return inventory


def run_graph(plan, *, graph_cache_root=None):
    """Run the identified current producer and an explicit read-only consumer.

    A cache root opts into the retained authenticated JSON cache. Native arrays
    remain in the plan's own store: every restored producer or consumer product
    revalidates those bytes before the graph releases its dependency. No retained
    R31 registry, old scientific binding or native R5 restart is loaded.
    """
    snapshot, executor, Store, runtime, modules = _components()
    binding = _Binding(plan, snapshot, runtime, modules)
    support = 'assembly-plan:'+binding.plan_id
    temporal = 'declared-final-output:'+binding.plan_id
    product_port = dict(quantity='ATLAS_TECTONIC_PRODUCT_V1', unit='1',
                        support_id=support, temporal_support=temporal)
    inspection_port = dict(quantity='ATLAS_TECTONIC_FIELD_INSPECTION_V1', unit='1',
                           support_id=support, temporal_support=temporal)
    producer_inputs = dict(plan_id=binding.plan_id, output='final')

    def validate_product(value):
        if type(value) is not dict:
            raise ValueError('identified JSON tectonics product required')
        snapshot.encoded(value)
        plan.verify_product(value)
        return value

    def validate_inspection(value):
        snapshot.exact(value, ('schema', 'source_product', 'source_product_sha256',
                              'fields', 'scope'), 'tectonics inspection')
        if (value['schema'] != 'atlas.w12-field-inspection.v1'
                or value['scope'] != 'Read-only field inspection; no downstream physics'
                or value['source_product_sha256'] != snapshot.sha(value['source_product'])):
            raise ValueError('tectonics inspection binding differs')
        validate_product(value['source_product'])
        if type(value['fields']) is not dict or not value['fields']:
            raise ValueError('complete field inspection inventory required')
        for name, field in value['fields'].items():
            snapshot.text(name)
            snapshot.exact(field, ('dtype', 'shape', 'nbytes', 'sha256'), 'field inspection')
            snapshot.text(field['dtype']); snapshot.digest(field['sha256'])
            if (type(field['shape']) is not list
                    or any(type(size) is not int or size < 0 for size in field['shape'])
                    or type(field['nbytes']) is not int or field['nbytes'] < 0):
                raise ValueError('bounded field shape/size required')
        return value

    def produce(context, inputs, incoming):
        if context != binding.context or inputs != producer_inputs or incoming:
            raise ValueError('exact assembly plan inputs and context required')
        value = validate_product(plan.run(output_index=None))
        return snapshot.emission(context, {'tectonics': product_port}, {'tectonics': value},
            evidence='Current supported assembly; physical owners and limitations remain in its product',
            source_status='WORKING NON-CANON', status='MODELLED')

    def inspect(context, inputs, incoming):
        if context != binding.context or inputs or set(incoming) != {'tectonics'}:
            raise ValueError('exact typed tectonics dependency required')
        value = incoming['tectonics']
        inventory = _field_inventory(plan, value, snapshot)
        inspection = dict(schema='atlas.w12-field-inspection.v1', source_product=deepcopy(value),
            source_product_sha256=snapshot.sha(value), fields=inventory,
            scope='Read-only field inspection; no downstream physics')
        return snapshot.emission(context, {'inspection': inspection_port}, {'inspection': inspection},
            evidence='Reads immutable identified tectonics fields through the declared graph dependency',
            source_status='WORKING NON-CANON', status='MODELLED')

    registry = {}
    for name, operation, port in ((PRODUCER, produce, product_port),
                                  (INSPECTOR, inspect, inspection_port)):
        registry[name] = dict(sha256=snapshot.sha(dict(binding=binding.identity,
            operation=name, port=port)), run=operation, verify=binding.verify)

    def stage(ident, operation, inputs, dependencies, outputs):
        return dict(stage_id=ident, category='plate_tectonics', producer_id=operation,
            producer_sha256=registry[operation]['sha256'], inputs=inputs,
            dependencies=dependencies, outputs=outputs, missing_inputs=[], mode='GENERATED',
            acceptance=dict(status='PENDING',
                evidence='Technical assembly and field consumption; no domain acceptance declared'))

    recipe = dict(schema='diadem.snapshot-graph-recipe.r11', context=binding.context,
        stages=[stage('tectonics', PRODUCER, producer_inputs, {}, {'tectonics': product_port}),
                stage('inspect', INSPECTOR, {},
                    {'tectonics': dict(stage_id='tectonics', output='tectonics', port=product_port)},
                    {'inspection': inspection_port})], required_categories=['plate_tectonics'],
        evidence='Public W12 current producer and explicit read-only downstream dependency')

    def restore(ident, record):
        values = record['row']['product']['values']
        if ident == 'tectonics':
            validate_product(values['tectonics'])
        elif ident == 'inspect':
            validate_inspection(values['inspection'])
        else:
            raise ValueError('unregistered W12 graph stage')

    cache = None if graph_cache_root is None else Store(
        Path(graph_cache_root), binding.identity, max_bytes=32 << 20)
    statistics = {}
    binding.verify()
    graph = executor.run(snapshot, recipe, registry, store=cache,
                         on_restore=restore, stats=statistics)
    binding.verify()
    rows = graph['state']['rows']
    return dict(schema='atlas.w12-public-graph-result.v1', source_status='WORKING NON-CANON',
        graph=graph, product=deepcopy(rows['tectonics']['product']['values']['tectonics']),
        inspection=deepcopy(rows['inspect']['product']['values']['inspection']),
        execution=statistics, binding=dict(identity=binding.identity, **deepcopy(binding.record)),
        plan_statistics=deepcopy(plan.statistics()), physical_acceptance=False,
        production_authorised=False, historical_checkpoint_compatibility=False)
