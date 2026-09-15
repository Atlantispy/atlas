"""JSON adapters for unchanged, source-bound physical scientific producers.

These are category component entrypoints, not assertions that regional science
is complete. Stateful terrain intervals stay ordered; separate catchments,
supports and explicit hazard scenarios may be scheduled independently.
"""
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from fractions import Fraction
import hashlib
import importlib.util
from pathlib import Path
import sys

from work.generator_runtime_r12 import _CapturedLoader
from work.generator_runtime_r12 import provenance as common
from work.generator_upgrade_r14 import provenance as ground
from work.generator_upgrade_r18 import consumer, model, provenance as geology, working
from work.generator_upgrade_r24.verification import Reader, _Clones

OPERATIONS = {
    'tectonic_snapshot': ('plate_tectonics',),
    'regional_geology': ('geology', 'topography_topology'),
    'geological_columns': ('geology', 'topography_topology'),
    'geological_incise': ('erosion_sediment_transport', 'topography_topology'),
    'geological_terrain_step': ('erosion_sediment_transport', 'topography_topology', 'hydrology'),
    'surface_water_route': ('hydrology',),
    'soil_stability': ('natural_hazards',),
}
TASK = Path(__file__).resolve().parents[2]
TECTONIC_SOURCE = TASK/'work/diadem_tectonics_r2/snapshot.py'
_TECTONICS = None


def _tectonics():
    global _TECTONICS
    if _TECTONICS is None:
        spec = importlib.util.spec_from_file_location('_r26_physical_tectonics',
            TECTONIC_SOURCE, loader=_CapturedLoader(TECTONIC_SOURCE))
        _TECTONICS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TECTONICS)
    return _TECTONICS


def _exact(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(label+': exact explicit JSON fields required')


def _plain(value):
    """Preserve all represented quantities and native dataclass fields exactly."""
    if isinstance(value, Fraction):
        return str(value)
    if is_dataclass(value):
        return _plain(asdict(value))
    if type(value) is dict:
        return {key: _plain(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_plain(item) for item in value]
    return value


def scientific(value):
    """Native execution durations are diagnostics, not reproducible science."""
    value = deepcopy(value)
    for key in ('elapsed_wall_seconds', 'regional_input_elapsed_wall_seconds'):
        if type(value) is dict and type(value.get('execution')) is dict:
            value['execution'].pop(key, None)
    return _plain(value)


def _identity(operation):
    if operation == 'tectonic_snapshot':
        module = _tectonics()
        raw = common.checked(TECTONIC_SOURCE)
        digest = hashlib.sha256(raw).hexdigest()
        if module._R12_EXECUTED_SHA256 != digest:
            raise ValueError('tectonic executed source changed; no repin')
        return {'source': digest, 'runtime': sys.version, 'executable': sys.executable}
    reader = Reader()
    try:
        source = geology if operation.startswith(('regional_', 'geological_')) else ground
        return _Clones(reader).module(source).identity()
    finally:
        reader.finish()


def _native():
    bundle, terrain = ground.backend()
    r6 = bundle
    for _ in range(5):
        r6 = r6.parent
    return terrain, r6.graph.load('work.generator_upgrade_r2.soil_physics')


def _q(value):
    return consumer.columns._q(value, 'explicit represented native quantity')


def _slope(module, record):
    row = deepcopy(record)
    for key in ('vertical_failure_depth_m', 'slope_degrees', 'bulk_unit_weight_n_m3',
                'effective_cohesion_pa', 'effective_friction_degrees', 'pore_pressure_pa'):
        row[key] = module.Interval(**row[key])
    roots = row['roots']
    for key in ('basal_cohesion_pa', 'maximum_active_depth_m'):
        roots[key] = module.Interval(**roots[key])
    row['roots'] = module.Roots(**roots)
    row['support'] = module.Support(**row['support'])
    return module.SlopeCase(**row)


def _snapshot(inputs, incoming):
    if 'snapshot' in inputs:
        if incoming:
            raise ValueError('snapshot supplied twice; use explicit snapshot or one predecessor')
        return inputs['snapshot']
    if len(incoming) != 1:
        raise ValueError('one exact geological snapshot predecessor required')
    return next(iter(incoming.values()))


def _package(inputs):
    _exact(inputs, ('package_dir', 'package_pins', 'domain_decisions'), 'tectonic snapshot')
    module = _tectonics()
    path = Path(inputs['package_dir'])
    if not path.is_absolute():
        raise ValueError('absolute immutable tectonic package required')
    names = {module.MANIFEST, *module.FILES.values()}
    if type(inputs['package_pins']) is not dict or set(inputs['package_pins']) != names:
        raise ValueError('all consumed tectonic package file pins required')
    for name in sorted(names):
        _, pin = module._read(path/name)
        if pin['sha256'] != inputs['package_pins'][name]:
            raise ValueError('tectonic input changed; no repin')
    decisions = inputs['domain_decisions']
    if decisions is not None:
        for source in decisions['source_refs']:
            common.checked(Path(source['path']), source['sha256'])
    return path


def _regional_sources():
    """Recheck current selected causal bytes without re-decoding their arrays."""
    spec = working.inputs()
    seen = set()
    for row in spec['resolved_field_inputs']:
        path = Path(spec['source_root'])/row['relative_path']
        key = (str(path), row['sha256'])
        if key not in seen:
            working.previous._read(path, row['sha256'], row['size_bytes'])
            seen.add(key)
    row = spec['sources']['validity_masks']
    working.previous._read(Path(spec['source_root'])/row['relative_path'], row['sha256'], row['size_bytes'])
    return spec


class Adapter:
    def __init__(self, operation, cache=True, cache_root=None, shared=None):
        if operation not in OPERATIONS:
            raise ValueError('unknown physical operation')
        self.operation = operation
        self.binding = _identity(operation)
        self.source_signature = common.sha({'operation': operation, 'native': self.binding})

    def verify(self):
        if _identity(self.operation) != self.binding:
            raise ValueError('physical native source/runtime changed; no repin')

    def prepare(self, inputs, incoming):
        common.encoded(inputs); common.encoded(incoming)
        operation = self.operation
        if operation == 'tectonic_snapshot':
            if incoming:
                raise ValueError('tectonic snapshot has no implicit predecessor inputs')
            _package(inputs)
        elif operation == 'regional_geology':
            _exact(inputs, ('supports', 'alternative', 'owner_input_sha256'), operation)
            if incoming or inputs['owner_input_sha256'] != working.INPUT_SHA:
                raise ValueError('explicit selected R18 source pin required')
            _regional_sources()
        elif operation == 'geological_columns':
            _exact(inputs, ('packet', 'supports', 'sampling', 'resolved', 'palette', 'reference_runoff_m_year'), operation)
            if incoming:
                raise ValueError('geological columns require explicit native inputs')
            consumer.regional._owner_source(inputs['packet']['owner_source'])
            consumer.regional._owner_source(inputs['packet']['source_package'])
        elif operation in ('geological_incise', 'geological_terrain_step'):
            names = {'forcing'} | ({'duration_years'} if operation == 'geological_incise' else set())
            if 'snapshot' in inputs:
                names.add('snapshot')
            _exact(inputs, names, operation)
            consumer.verify(_snapshot(inputs, incoming))
        elif operation == 'surface_water_route':
            _exact(inputs, ('state', 'local_runoff_m3', 'connectors', 'duration_years'), operation)
            if incoming:
                raise ValueError('surface routing requires its explicit current native state')
        elif operation == 'soil_stability':
            _exact(inputs, ('shape', 'cells'), operation)
            if incoming:
                raise ValueError('hazard input cases must bind their explicit water/material states')

    def run(self, inputs, incoming):
        self.prepare(inputs, incoming)
        return self.produce(self.operation, inputs, incoming)

    @staticmethod
    def produce(operation, inputs, incoming):
        """Unchanged native call, shared by direct baseline and cached adapter."""
        if operation == 'tectonic_snapshot':
            result = _tectonics().build_snapshot(Path(inputs['package_dir']), inputs['domain_decisions'])
        elif operation == 'regional_geology':
            result = working.build(inputs['supports'], inputs['alternative'])
        elif operation == 'geological_columns':
            result = model.build(**inputs)
        elif operation == 'geological_incise':
            result = consumer.incise(_snapshot(inputs, incoming), inputs['forcing'], inputs['duration_years'])
        elif operation == 'geological_terrain_step':
            result = consumer.terrain_step(_snapshot(inputs, incoming), inputs['forcing'])
        elif operation == 'surface_water_route':
            native, _ = _native()
            connectors = []
            for item in inputs['connectors']:
                row = dict(item, length_m=_q(item['length_m']))
                if row['outlet_elevation_m'] is not None:
                    row['outlet_elevation_m'] = consumer.regional._signed(row['outlet_elevation_m'])
                connectors.append(native.Connector(**row))
            result = native.route_water(native.LandscapeState.from_dict(inputs['state']),
                {key: _q(value) for key, value in inputs['local_runoff_m3'].items()},
                tuple(connectors), duration_years=_q(inputs['duration_years']))
        else:
            _, module = _native()
            result = module.stability_grid(tuple(inputs['shape']), tuple(
                tuple(_slope(module, case) for case in cases) for cases in inputs['cells']))
        return scientific(result)

    def validate_result(self, result, inputs, incoming):
        self.prepare(inputs, incoming)
        common.encoded(result)
        if self.operation in ('regional_geology', 'geological_columns'):
            consumer.verify(result)
        elif self.operation == 'tectonic_snapshot':
            if result.get('validation', {}).get('category_complete') is not False or set(
                    result.get('products', {})) != set(_tectonics().PRODUCT_NAMES):
                raise ValueError('unpromoted complete native tectonic product inventory required')
        elif self.operation == 'soil_stability':
            if result.get('schema') != 'diadem.shallow-soil-stability-grid.r2':
                raise ValueError('native bounded stability result required')
        elif self.operation == 'surface_water_route':
            local = sum(map(Fraction, result['local_runoff_m3'].values()), Fraction())
            exports = sum(map(Fraction, result['external_exports_m3'].values()), Fraction())
            if local != exports:
                raise ValueError('native exact routed water conservation differs')
        else:
            if result.get('r18_input_scientific_sha256') != _snapshot(inputs, incoming)['execution']['scientific_sha256']:
                raise ValueError('native geological consumer parent identity differs')


def baseline(operation, inputs):
    if operation not in OPERATIONS:
        raise ValueError('unknown physical operation')
    return Adapter.produce(operation, deepcopy(inputs), {})


def fixtures():
    """Small explicit real producer inputs; synthetic forcing stays synthetic."""
    from work.generator_upgrade_r18 import composite
    evidence = 'SYNTHETIC TEST R26 finite physical adapter parity; not Diadem calibration'
    source = {'path': str(Path(__file__).resolve()),
              'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    material = composite.create([
        {'unit_id': 'test-A', 'bulk_weight': '1/3', 'grain_density_kg_m3': 2700, 'porosity': '1/50'},
        {'unit_id': 'test-B', 'bulk_weight': '2/3', 'grain_density_kg_m3': 2500, 'porosity': '1/10'}],
        '7/300000', phase='bedrock', evidence=evidence)
    mid = material['material_id']
    columns = {'packet': {'context': {'world_id': 'SYNTHETIC_NOT_DIADEM', 'snapshot_id': 'R26_NATIVE_CHECK',
        'spatial_frame_id': 'LOCAL_METRES_EAST_SOUTH', 'vertical_reference': 'LOCAL_METRES_UP'},
        'source_status': 'SYNTHETIC TEST', 'evidence': evidence, 'owner_source': source, 'source_package': source},
        'supports': {key: {'xy_m': [x, 0], 'area_m2': 1} for key, x in (('upper', 0), ('lower', 10))},
        'sampling': {'samples': {'upper': {}, 'lower': {}}},
        'resolved': {key: {'basal_elevation_m': base, 'translation_m': 0,
            'layers': [{'compartment_id': 'test-body', 'material_id': mid, 'thickness_m': 10}],
            'interpretation': {'status': 'SYNTHETIC TEST'}} for key, base in (('upper', 0), ('lower', -1))},
        'palette': {mid: material}, 'reference_runoff_m_year': '1'}
    snapshot = scientific(model.build(**columns))
    connectors = [dict(connector_id='upper-lower', source_id='upper', receiver_id='lower',
        length_m=10, outlet_elevation_m=None, evidence=evidence),
        dict(connector_id='outlet', source_id='lower', receiver_id=None,
        length_m=10, outlet_elevation_m=8, evidence=evidence)]
    def prop(name, value, unit):
        return dict(name=name, value=value, unit=unit, evidence=evidence, status='SYNTHETIC TEST')
    terrain = {'duration_years': .001, 'local_runoff_m3': {'upper': .01, 'lower': 0},
        'connectors': connectors,
        'erosion_laws': [{'material_id': mid, 'phase': phase,
            'k_per_year': prop('erosion_coefficient_at_reference_runoff', '7/300000', '1/year'),
            'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}
            for phase in ('bedrock', 'mobile_sediment')],
        'sediment_laws': [{'material_id': mid, 'settling_m_year': 1,
            'deposited_porosity': .4, 'deposition_order': 0, 'evidence': evidence}],
        'controls': {'max_relief_change_fraction': .25, 'max_solid_liquid_ratio': .1, 'evidence': evidence},
        'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    def interval(value, unit):
        return dict(lower=value, upper=value, unit=unit, evidence=evidence, source_status='SYNTHETIC TEST')
    case = dict(case_id='R26-shallow-static', regime='SHALLOW_TRANSLATIONAL_SOIL',
        vertical_failure_depth_m=interval(1, 'm'), slope_degrees=interval(45, 'degree'),
        bulk_unit_weight_n_m3=interval(20000, 'N/m3'), effective_cohesion_pa=interval(1000, 'Pa'),
        effective_friction_degrees=interval(45, 'degree'), pore_pressure_pa=interval(2000, 'Pa'),
        roots=dict(basal_cohesion_pa=interval(500, 'Pa'), maximum_active_depth_m=interval(2, 'm'), mode='BASAL', evidence=evidence),
        support=dict(kind='SCALAR_REFERENCE', output_resolution_m=None, process_support_m=None,
            scenario_id='R26-parity', evidence=evidence), water_state_id='synthetic-water',
        material_state_id='synthetic-material', evidence=evidence)
    module = _tectonics()
    package = TASK/'outputs/diadem-tectonics-review-r1/verified-02/sandbox/work/stage4-rebuild'
    pins = {name: module._read(package/name)[1]['sha256'] for name in (module.MANIFEST, *module.FILES.values())}
    spec = working.inputs()
    point = next(iter(working.case_supports(spec).items()))
    return {
        'tectonic_snapshot': dict(package_dir=str(package), package_pins=pins, domain_decisions=None),
        'regional_geology': dict(supports=dict([point]), alternative='DEFAULT', owner_input_sha256=working.INPUT_SHA),
        'geological_columns': columns,
        'geological_incise': dict(snapshot=snapshot, duration_years='1/1000', forcing={key: dict(
            discharge_m3_year=10., hydraulic_slope=.1, source_status='SYNTHETIC TEST', evidence=evidence)
            for key in ('upper', 'lower')}),
        'geological_terrain_step': dict(snapshot=snapshot, forcing=terrain),
        'surface_water_route': dict(state=snapshot['scientific']['state'], local_runoff_m3=terrain['local_runoff_m3'],
            connectors=connectors, duration_years=terrain['duration_years']),
        'soil_stability': dict(shape=[1, 1], cells=[[case]]),
    }
