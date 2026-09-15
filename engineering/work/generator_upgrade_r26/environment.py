"""Bounded native environmental producers for the common R26 executor.

No scientific formula, tolerance, unknown mask or source status is replaced.
Independent caller-declared units can be scheduled together; a transect or soil
time step remains native and sequential. Resource arrays use lossless transport.
"""
import base64
import builtins
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
from types import ModuleType

import numpy as np
import scipy

from work.generator_runtime_r12 import provenance as common
from work.generator_upgrade_r24.verification import Reader

OPERATIONS = {
    'climate_transect': ('climate', 'precipitation'),
    'precipitation_phase': ('precipitation',),
    'biome_cell': ('biomes',),
    'soil_heat_water': ('soils_ground_conditions',),
    'natural_resources': ('resources_land_suitability',),
}
LIMIT = common.LIMIT
ROOT = Path(__file__).resolve().parents[2]


def _sha(value):
    return common.sha(value)


def _runtime():
    return {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
            'platform': platform.platform(), 'numpy': np.__version__,
            'scipy': scipy.__version__, 'optimisation': sys.flags.optimize,
            'environment': {key: os.environ.get(key) for key in
                ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                 'PYTHONHASHSEED', 'MKL_CBWR')}}


def _reviewed_runtime():
    import pandas
    import shapely
    import affine
    return dict(_runtime(), pandas=pandas.__version__, shapely=shapely.__version__,
                geos=shapely.geos_version_string, affine=affine.__version__)


def pack_array(value):
    """Exact primitive ndarray bytes, including NaN payloads and signed zero."""
    array = np.asarray(value)
    if array.dtype.kind not in 'biuf' or array.dtype.itemsize > 8 or not 1 <= array.ndim <= 4:
        raise ValueError('bounded primitive numerical array required')
    if any(n < 0 for n in array.shape) or array.nbytes > LIMIT:
        raise ValueError('bounded numerical array required')
    raw = np.ascontiguousarray(array).tobytes()
    data = base64.b64encode(raw).decode('ascii')
    if len(data) > LIMIT:
        raise ValueError('encoded array exceeds unchanged 8 MiB envelope; use declared tiles')
    return {'schema': 'diadem.lossless-array.r26', 'dtype': array.dtype.str,
            'shape': list(array.shape), 'byte_length': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'data': data}


def unpack_array(record):
    if (type(record) is not dict or set(record) !=
            {'schema', 'dtype', 'shape', 'byte_length', 'sha256', 'data'}
            or record['schema'] != 'diadem.lossless-array.r26'):
        raise ValueError('exact lossless array record required')
    shape, dtype = record['shape'], record['dtype']
    if (type(shape) is not list or not 1 <= len(shape) <= 4
            or any(type(n) is not int or n < 0 for n in shape)
            or type(dtype) is not str or len(dtype) > 8):
        raise ValueError('bounded explicit numerical array shape/dtype required')
    dtype = np.dtype(dtype)
    if dtype.kind not in 'biuf' or dtype.itemsize > 8 or dtype.str != record['dtype']:
        raise ValueError('canonical primitive numerical dtype required')
    size = math.prod(shape)*dtype.itemsize
    data = record['data']
    if (type(record['byte_length']) is not int or record['byte_length'] != size
            or not 0 <= size <= LIMIT or type(data) is not str or len(data) > LIMIT
            or type(record['sha256']) is not str or len(record['sha256']) != 64):
        raise ValueError('bounded exact array byte length required')
    raw = base64.b64decode(data, validate=True)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('array content digest/length differs')
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


def _reviewed_human_resource():
    """Private captured reviewed module, declared sources, fresh verifier.

All pins in both reviewed declarations are retained, so settlement/transport
adapters may reuse this loader. Historical top-level workflows are never run.
"""
    folder = ROOT/'work/module_review_upstream_r1'
    prior = ROOT/'work/human_resource_corrections_r1'
    reader = Reader()
    raw = {}
    sources = {}
    try:
        for path in (folder/'binding.py', folder/'human_resource.py',
                     folder/'SOURCE_PINS.json', prior/'successors.py', prior/'source_pins.json'):
            contents = reader.checked(path)
            raw[path] = contents
            sources[str(path)] = hashlib.sha256(contents).hexdigest()
        for path in (folder/'SOURCE_PINS.json', prior/'source_pins.json'):
            for pin in json.loads(raw[path]).values():
                if type(pin) is dict and set(pin) >= {'path', 'sha256'}:
                    source = Path(pin['path'])
                    reader.checked(source, pin['sha256'])
                    if str(source) in sources and sources[str(source)] != pin['sha256']:
                        raise ValueError('conflicting reviewed source pins')
                    sources[str(source)] = pin['sha256']
        modules = {}
        for name in ('binding', 'human_resource'):
            path = folder/(name+'.py')
            module = ModuleType('_r26_reviewed_'+name)
            module.__file__ = str(path)
            def local_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == 'binding' and not level:
                    if not fromlist or any(item not in vars(modules['binding']) for item in fromlist):
                        raise ValueError('undeclared reviewed local import')
                    return modules['binding']
                return builtins.__import__(name, globals, locals, fromlist, level)
            module.__dict__['__builtins__'] = dict(vars(builtins), __import__=local_import)
            exec(compile(raw[path], str(path), 'exec', dont_inherit=True), module.__dict__)
            modules[name] = module
    finally:
        reader.finish()
    runtime = _reviewed_runtime()
    modules['human_resource']._R26_RUNTIME = deepcopy(runtime)
    pins = tuple(sorted(sources.items()))
    def verify():
        current = Reader()
        try:
            for path, digest in pins:
                current.checked(path, digest)
            if _reviewed_runtime() != runtime:
                raise ValueError('reviewed native runtime changed')
        finally:
            current.finish()
    verify()
    return modules['human_resource'], deepcopy(sources), verify


class Adapter:
    def __init__(self, operation, cache=True, cache_root=None, *, shared=None):
        if operation not in OPERATIONS:
            raise ValueError('unknown environmental native operation')
        self.operation = operation
        self._shared = {} if shared is None else shared
        self._runtime = _runtime()
        if operation in ('climate_transect', 'precipitation_phase', 'biome_cell'):
            from work.generator_upgrade_r14 import provenance as ground
            if 'legacy_environment' not in self._shared:
                # Existing R14 backend holds captured code, not trusted source
                # digests/results. Complete fresh verification below is retained.
                self._shared['legacy_environment'] = ground.backend()[0]
            self.bundle = self._shared['legacy_environment']
            self.r8 = self.bundle.parent.parent.parent
            self.r6 = self.r8.parent.parent
            self.native = (self.r8.graph.load('work.generator_upgrade_r8.biomes')
                           if operation == 'biome_cell' else self.r6.graph.load(
                               'work.generator_upgrade_r4.'+('climate' if operation == 'climate_transect' else 'hydromet')))
            loader = None if self._shared.get('fresh_science_baseline') else ground.identity()
            execution = (common.execution_identity(self.bundle) if loader is None
                         else deepcopy(ground._BACKEND_ID))
            self.identity = {'native_science': self.bundle.source_sha256,
                             'runtime': self._runtime, 'execution': execution, 'loader': loader}
            def verify_science():
                common.checked(common.SEAL, common.SEAL_SHA)
                common.verify_execution(self.bundle, execution, full=True)
                if loader is not None and ground.identity() != loader:
                    raise ValueError('captured scientific backend loader changed')
            self._check = verify_science
        elif operation == 'soil_heat_water':
            from work.generator_upgrade_r13 import soil, audit, provenance
            self.native, self.audit = soil, audit
            self.identity = provenance.identity()
            self._check = lambda: provenance.verify(self.identity)
        else:
            if 'reviewed_human_resource' not in self._shared:
                self._shared['reviewed_human_resource'] = _reviewed_human_resource()
            self.native, sources, self._check = self._shared['reviewed_human_resource']
            self.identity = {'sources': sources, 'runtime': self.native._R26_RUNTIME}
        self.source_signature = _sha({'operation': operation, 'execution': self.identity})
        self.verify()

    def verify(self):
        self._check()
        if _runtime() != self._runtime:
            raise ValueError('environmental execution runtime changed')
        return self.source_signature

    def run(self, inputs, incoming):
        if type(inputs) is not dict or type(incoming) is not dict or set(inputs) & set(incoming):
            raise ValueError('disjoint explicit environmental inputs/dependencies required')
        arguments = deepcopy({**inputs, **incoming})
        common.encoded(arguments)
        native = self.native
        if self.operation == 'climate_transect':
            if set(arguments) != {'cells', 'atmosphere', 'controls'}:
                raise ValueError('exact climate transect inputs required')
            return native.generate([native.Cell(**row) for row in arguments['cells']],
                                   native.AirMass(**arguments['atmosphere']),
                                   native.Controls(**arguments['controls']))
        if self.operation == 'precipitation_phase':
            arguments['law'] = native.PhaseLaw(**arguments['law'])
            # Same native convention used by hydromet's pipeline: exact
            # rational amounts are decimal/fraction strings, never float casts.
            return self.r8.graph.load('work.generator_upgrade_r8.seasonal').plain(
                native.partition_precipitation(**arguments))
        if self.operation == 'biome_cell':
            result = native.classify_cell(**arguments)
            # Native R8 uses JSON serialisation to turn integer legend-code keys
            # into their exact string representation; no metric values change.
            return json.loads(json.dumps(result, allow_nan=False))
        if self.operation == 'soil_heat_water':
            if set(arguments) != {'model', 'state', 'event', 'controls'}:
                raise ValueError('exact coupled soil inputs required')
            result = native.advance(**arguments)
            if result.get('status') == 'MODELLED':
                self.audit.event(arguments['model'], arguments['event'], result, arguments['controls'])
            return result
        if set(arguments) != {'register', 'arrays', 'shape'}:
            raise ValueError('exact native resource register, arrays and shape required')
        arrays = {key: unpack_array(value) for key, value in arguments['arrays'].items()}
        config, products = native.build_resource(arguments['register'], arrays, shape=arguments['shape'])
        return {'schema': 'diadem.native-resource-arrays.r26', 'config': config,
                'products': {key: [pack_array(value) for value in values]
                             for key, values in products.items()}}


def fixtures():
    """Tiny declared numerical examples, never substituted Diadem inputs."""
    evidence = 'SYNTHETIC TEST: R26 bounded native adapter timing; no Diadem calibration'
    shared = {}
    climate = Adapter('climate_transect', cache=False, shared=shared)
    reference = climate.r6.reference.recipe()
    climate_input = {'cells': [dict(row, elevation_m=300 if row['cell_id']=='upper' else 0)
                               for row in reference['transect']],
                     'atmosphere': reference['events'][0]['atmosphere'],
                     'controls': reference['events'][0]['climate_controls']}
    phase = {'precipitation_m_s': 0.000001, 'temperature_c': 0.,
             'law': {'snow_at_or_below_c': -1., 'rain_at_or_above_c': 2.,
                     'temperature_basis': 'AIR_TEMPERATURE', 'evidence': evidence},
             'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    r8 = climate.r8
    recipe = r8.reference.recipe(r8)
    metric = 'active_actual_to_potential_transpiration_ratio'
    pft_results = {family['family_id']: {key: {
        'schema': 'diadem.pft-seasonal-admissibility.r8', 'pft_id': key,
        'status': 'PASS', 'metric_units': {metric: '1'}, 'metrics': {metric: .8},
        'metric_intervals': {metric: [.8, .8]}}
        for key in recipe['pfts']} for family in recipe['families']}
    biome = {'cell_id': 'synthetic', 'domain': {'kind': 'LAND', 'evidence': evidence,
             'source_status': 'SYNTHETIC TEST'}, 'families': recipe['families'],
             'pft_results': pft_results,
             'climate_metrics': {key: {'value': value, 'unit': unit, 'evidence': evidence,
                                      'source_status': 'SYNTHETIC TEST'}
                                for key, value, unit in (
                                    ('warmest_month_temperature_c', 19., 'degC'),
                                    ('snow_persistence_fraction', .1, '1'),
                                    ('annual_precipitation_to_reference_pet_ratio', 1., '1'))},
             'pft_guilds': {key: {'guild': value['guild'], 'evidence': value['evidence']}
                           for key, value in recipe['pfts'].items()},
             'controls': recipe['classification_controls']}
    from work.generator_upgrade_r13 import soil
    provenance = {'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    model = {'layers': [dict(layer_id='synthetic', thickness_m=.1, theta_r=.05,
        theta_s=.45, vg_alpha_per_m=2., vg_n=1.6, mualem_l=.5,
        saturated_conductivity_m_s=1e-6, ice_impedance=7., dry_heat_capacity_j_m3_k=1.4e6,
        conductivity_dry_w_m_k=.25, conductivity_saturated_unfrozen_w_m_k=1.6,
        conductivity_saturated_frozen_w_m_k=2.2, **provenance)],
        'constants': {'water_density_kg_m3': 1000., 'water_heat_capacity_j_kg_k': 4180.,
                      'ice_heat_capacity_j_kg_k': 2100., 'latent_heat_j_kg': 334000.,
                      'melting_temperature_k': 273.15, 'gravity_m_s2': 9.80665}, **provenance}
    event = {'duration_s': 10., 'surface_water_flux_m_s': 1e-7,
             'surface_water_temperature_k': 274.,
             'top_heat': {'kind': 'flux', 'value': 1., **provenance},
             'bottom_heat': {'kind': 'flux', 'value': 0., **provenance},
             'bottom_water': {'kind': 'noflow', **provenance},
             'root_withdrawal_m_s': [0.], **provenance}
    controls = {'initial_step_s': 10., 'min_step_s': 1e-4, 'max_step_s': 1000.,
        'water_atol_m': 1e-8, 'water_fraction_atol': 1e-5, 'energy_atol_j_m2': .1,
        'head_atol_m': 1e-3, 'temperature_atol_k': 1e-3, 'relative_tolerance': 1e-4,
        'nonlinear_water_atol_m': 1e-11, 'nonlinear_energy_atol_j_m2': 1e-4,
        'min_head_m': -1000., 'max_head_m': 100., 'min_temperature_k': 230.,
        'max_temperature_k': 330., 'max_steps': 2000, 'max_nonlinear_evaluations': 80}
    soil_input = {'model': model, 'state': soil.initial_state(model, [-1.], [274.]),
                  'event': event, 'controls': controls}
    resource = {'register': {'goods': [{'id': 'volcanic_building_stone',
        'name': 'Synthetic stone', 'category': 'stone', 'canon_status': 'UNKNOWN',
        'confidence': 'LOW', 'evidence': evidence}]},
        'arrays': {key: pack_array(np.ones((2, 3), np.float32)) for key in
            ('volcanic_stable', 'stable', 'fracture_flow_local', 'volcanic_stone_host', 'land', 'geo_unc')},
        'shape': [2, 3]}
    return {'climate_transect': climate_input, 'precipitation_phase': phase,
            'biome_cell': biome, 'soil_heat_water': soil_input, 'natural_resources': resource}


def baseline(operation, inputs):
    # Separate native launches previously reconstructed the sealed scientific
    # bundle. Keep this measured baseline explicit rather than timing the new
    # loaded-backend reuse and calling it the old launcher.
    shared = ({'legacy_environment': common.load_science(), 'fresh_science_baseline': True}
              if operation in ('climate_transect', 'precipitation_phase', 'biome_cell') else None)
    adapter = Adapter(operation, cache=False, shared=shared)
    adapter.verify()
    result = adapter.run(inputs, {})
    adapter.verify()
    return result
