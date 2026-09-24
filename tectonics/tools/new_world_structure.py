"""Grid-independent, seeded initial lithosphere; not a reconstructed history.

SPDX-License-Identifier: AGPL-3.0-only
Feature geometry and columns use native W01 records and conservative sampling.
This adapter stays outside the source-bound native package. No plate membership,
mesh resolution, clock or global RNG is used to choose geological features.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import time

from new_world_contract import ContractError, canonical_bytes, parse_json, validate_plan

METHOD = 'atlas.initial-lithosphere.v1'
SOURCE = 'initial-lithosphere-scenario'
MYR = 365.25 * 86400 * 1e6
_FILE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()
REFERENCES = (
    'https://se.copernicus.org/articles/10/1785/2019/',
    'https://agupubs.onlinelibrary.wiley.com/doi/10.1029/92JB01749',
    'https://aspect-documentation.readthedocs.io/en/latest/parameters/Initial_20temperature_20model.html',
    'https://se.copernicus.org/articles/14/1155/2023/',
)


@dataclass(frozen=True, slots=True)
class WorldStructure:
    state: object
    report: dict

    @property
    def structure_id(self):
        return _hash(self.report)


def _hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _fail(message):
    raise ContractError('STRUCTURE_REFUSED', message)


def _source_binding():
    import new_world_thermal as thermal
    digest = hashlib.sha256(_FILE.read_bytes()).hexdigest()
    if digest != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Initial-structure adapter changed while loaded.')
    try:
        thermal_hash = thermal.source_hash()
    except ValueError as exc:
        raise ContractError('SOURCE_MISMATCH', 'Initial thermal adapter changed while loaded.') from exc
    return dict(structure_sha256=digest, thermal_sha256=thermal_hash)


def _inputs(plan):
    # Explicit dependency slice: changing plate count/resolution must not redraw
    # geology. Gravity is not used by this geometry/constant-property thermal IC.
    return dict(seed=plan['request']['seed'], frame=plan['request']['frame'],
        epoch=plan['request']['epoch'], radius_m=plan['resolved_settings']['radius_m'],
        continental_fraction=plan['resolved_settings']['continental_fraction'],
        streams={k: plan['streams'][k] for k in
                 ('continental_structure', 'crustal_structure', 'thermal_structure')})


def _draw(seed, label):
    raw = hashlib.sha256(bytes.fromhex(seed) + b'\0' + label.encode('ascii')).digest()
    return (int.from_bytes(raw[:8], 'big') >> 11) * 2.**-53


def _rotation(seed):
    """Shoemake uniform unit-quaternion rotation from three named draws."""
    import numpy as np
    u, v, w = (_draw(seed, 'rotation/'+str(i)) for i in range(3))
    x, y = math.sqrt(1-u)*math.sin(2*math.pi*v), math.sqrt(1-u)*math.cos(2*math.pi*v)
    z, q = math.sqrt(u)*math.sin(2*math.pi*w), math.sqrt(u)*math.cos(2*math.pi*w)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*q), 2*(x*z+y*q)],
                     [2*(x*y+z*q), 1-2*(x*x+z*z), 2*(y*z-x*q)],
                     [2*(x*z-y*q), 2*(y*z+x*q), 1-2*(x*x+y*y)]])


def _footprints(sphere, seed, fraction, budget, check):
    """Three disjoint irregular minor-arc provinces, solved to exact area.

    The minority crust type occupies the polygons; the other is the background.
    This is a declared shape prior, not an inferred coastline or elevation map.
    Caps stay below 58 degrees, while centres are 120 degrees apart. That proves
    disjointness without approximate polygon clipping or a mesh-dependent mask.
    """
    import numpy as np
    from atlas_tectonics import SphericalChart, SphericalGeometry
    rotation = _rotation(seed)
    if fraction in (0., 1.):
        return (), rotation
    minority = min(fraction, 1-fraction)
    weights = [0.95 + 0.1*_draw(seed, 'area/'+str(i)) for i in range(3)]
    total = math.fsum(weights)
    results = []
    for i, weight in enumerate(weights):
        check()
        angle = 2*math.pi*i/3
        centre = rotation @ np.array([math.cos(angle), math.sin(angle), 0.])
        chart = SphericalChart(sphere, tuple(centre))
        theta = np.arange(32) * (2*math.pi/32)
        phase = 2*math.pi*_draw(seed, 'shape/'+str(i))
        radial = 1 + .055*np.sin(3*theta+phase) + .025*np.cos(5*theta-2*phase)
        target = 4*math.pi*minority*weight/total

        def ring(scale):
            xy = scale*radial[:, None]*np.column_stack((np.cos(theta), np.sin(theta)))
            return chart._unproject(xy)

        def area(unit):
            other = np.roll(unit, -1, axis=0)
            numerator = np.einsum('ij,j->i', np.cross(unit-centre, other-centre), centre)
            denominator = 1 + unit@centre + other@centre + np.einsum('ij,ij->i', unit, other)
            return math.fsum(2*np.arctan2(numerator, denominator))

        lo, hi = 0., math.tan(math.radians(58))/float(radial.max())
        if area(ring(hi)) < target:
            _fail('Requested province area is outside the fixed shape envelope.')
        # Fixed bisection count, not random retries. Only 32 directions evaluated;
        # construct/index a native geometry once, after solving its physical area.
        for _ in range(56):
            mid = (lo+hi)/2
            if area(ring(mid)) < target:
                lo = mid
            else:
                hi = mid
        unit = ring((lo+hi)/2)
        geometry = SphericalGeometry.polygon(unit, chart=chart, budget=budget)
        if abs(geometry.area_steradians-target) > 2e-11*target:
            _fail('Spherical province area did not meet its declared tolerance.')
        results.append((f'province-{i}', geometry, unit, (lo+hi)/2))
    return tuple(results), rotation


def generate_structure(plan):
    """Build a finite Earth-like static scenario, not plate motion or terrain."""
    started = time.perf_counter()
    plan = validate_plan(plan)
    binding = _source_binding()
    inputs = _inputs(plan)
    import numpy as np
    from atlas_tectonics import (SphericalFrame, SphericalChart, SphericalGeometry,
        GeologySource, GeologicalDomain, GeologicalCase, FeatureGeometry,
        GeologicalProvince, SurfaceSelector, FeaturePrecedence, WeakZoneDescription,
        MaterialCohort, CohortDescription, GeologicalLayer, LayerComponent,
        ColumnDescription, ThermalInitialProfile, PrecursorState, InputOrigin,
        CoolingHistory, earth_material_library)
    from atlas_tectonics.resources import WorkBudget, MemoryLimitError
    from atlas_tectonics.reuse import ExecutionContext
    from new_world_thermal import ocean_profile, continental_profile
    radius = inputs['radius_m']
    # A named thin-lithosphere scenario; no silent Earth-thickness extrapolation
    # inside a tiny planet. This is a model-admission ratio, not an accuracy claim.
    if radius < 3e6:
        _fail('This Earth-like initial scenario requires radius >= 3000 km (150 km/R <= 0.05).')
    budget = WorkBudget(plan['request']['resources']['max_work_bytes'])

    def check():
        if time.perf_counter()-started >= plan['request']['resources']['max_wall_seconds']:
            raise ContractError('TIME_LIMIT', 'Initial-structure time budget expired.')

    try:
        # Bound adapter arrays/tables plus current execution identity before work;
        # native constructors additionally account their own temporary workspace.
        with budget.reserve(12 << 20, category='initial-structure-adapter'):
            with ExecutionContext() as context:
                sphere = SphericalFrame(radius, inputs['frame']['id'])
                f = inputs['continental_fraction']
                footprints, rotation = _footprints(sphere, inputs['streams']['continental_structure'], f, budget, check)
                background = 'oceanic' if f <= .5 else 'continental'
                minority = 'continental' if background == 'oceanic' else 'oceanic'
                kinds = [('background', background)] + [(name, minority) for name, *_ in footprints]
                if f == 1.:
                    kinds = [('background', 'continental')]
                library = earth_material_library()
                material_ids = ('rock.basalt', 'rock.gabbro', 'rock.granite', 'rock.peridotite')
                materials, references = library.definitions(material_ids)
                statement = ('Seeded static Earth-like initial-condition scenario, not geological history. '
                    'Three rotated irregular minority-crust provinces, disjoint 58-degree caps; '
                    'continental fraction is crustal surface coverage, not dry land. '
                    'Dry bulk-reference layers; no added pore volume. Catalogue properties are '
                    'reference-condition values, not hot-state density/rheology. Separate explicit '
                    'constant thermal laws generate the initial profiles. Ocean basal thermal plate '
                    'thickness is 125 km, not age-dependent mechanical lithosphere. Inherited zones '
                    'are prescribed traces with unknown strength, not active faults or damage. '
                    'No lateral thermal equilibration, stress, plate motion, slabs or water are inferred.')
                source = GeologySource(SOURCE, 'generated', statement, REFERENCES,
                                       content_sha256=_hash(dict(inputs=inputs, binding=binding, method=METHOD)))
                columns, cohorts, profiles, cooling, details = [], [], [], [], []
                now = inputs['epoch']['time_s']
                for name, kind in kinds:
                    check()
                    crust_seed, thermal_seed = (inputs['streams'][k] for k in ('crustal_structure', 'thermal_structure'))
                    value = lambda label: _draw(crust_seed, name+'/'+label)
                    if kind == 'continental':
                        crust = 30000 + 15000*value('thickness')
                        litho = 110000 + 40000*value('lithosphere')
                        upper = crust*(.45+.15*value('upper-fraction'))
                        ages = (400+2600*value('formation'))*MYR
                        stack = [('upper-crust', 'crust', upper, 'rock.granite'),
                                 ('lower-crust', 'crust', crust-upper, 'rock.gabbro'),
                                 ('mantle', 'lithospheric_mantle', litho-crust, 'rock.peridotite')]
                        thermal = continental_profile((0., upper, crust, litho),
                            (2.5, 2.5, 3.3), (1e-6, .25e-6, .02e-6))
                        cooling_age = None
                        cooling.append(CoolingHistory(name+'-thermal', SOURCE, None,
                            'Prescribed steady layered geotherm; no cooling onset inferred from crust formation.'))
                    else:
                        crust, litho = 6200+1800*value('thickness'), 125000.
                        cooling_age = (10+110*_draw(thermal_seed, name+'/cooling-age'))*MYR
                        ages = cooling_age
                        stack = [('basalt', 'crust', .25*crust, 'rock.basalt'),
                                 ('gabbro', 'crust', .75*crust, 'rock.gabbro'),
                                 ('mantle', 'lithospheric_mantle', litho-crust, 'rock.peridotite')]
                        thermal = ocean_profile(cooling_age, budget=budget)
                        cooling.append(CoolingHistory(name+'-thermal', SOURCE, now-cooling_age))
                    layers = []
                    for label, role, thickness, material in stack:
                        cid = name+'-'+label
                        cohorts.append(CohortDescription(MaterialCohort(cid, material, name,
                            None if role == 'lithospheric_mantle' else now-ages), SOURCE))
                        layers.append(GeologicalLayer(cid, role, thickness,
                            (LayerComponent(cid, 1.),), 0., SOURCE))
                    profiles.append(ThermalInitialProfile(name+'-thermal', SOURCE, 'tabulated',
                        depths_m=thermal.depths_m, temperatures_k=thermal.temperatures_k))
                    columns.append(ColumnDescription(name, kind, tuple(layers), litho, name+'-thermal', SOURCE))
                    details.append(dict(column_id=name, crust_type=kind, crust_formation_age_s=ages,
                        cooling_age_s=cooling_age, thermal_model=thermal.descriptor(),
                        interpolation_error_bound_k=thermal.max_error_bound_k,
                        ocean_formation_cooling_assumption=(
                            'Crust formed then cooled without reheating.' if kind == 'oceanic' else None)))
                geometries = [FeatureGeometry(name, geom, SOURCE) for name, geom, *_ in footprints]
                provinces = [GeologicalProvince('background', 'background', SurfaceSelector('domain'), SOURCE)]
                provinces.extend(GeologicalProvince(name, name, SurfaceSelector('geometry', (name,)), SOURCE)
                                 for name, *_ in footprints)
                zones = []
                # Inherited structures live inside continental crust. Pure ocean
                # worlds intentionally contain no guessed continental inheritance.
                traces = [(name, geom.chart, scale*.4) for name, geom, _, scale in footprints
                          if minority == 'continental']
                if background == 'continental':
                    traces = [('background', SphericalChart(sphere, tuple(rotation @ np.array([0., 0., 1.]))), .12)]
                for name, chart, size in traces:
                    xyz = chart._unproject(np.array([[-size, -.08*size], [0., .1*size], [size, 0.]]))
                    key = name+'-inherited'
                    geometries.append(FeatureGeometry(key, SphericalGeometry.polyline(xyz, chart=chart, budget=budget), SOURCE))
                    zones.append(WeakZoneDescription(key, SurfaceSelector('geometry', (key,)),
                        0., next(c.crust_thickness_m for c in columns if c.column_id == name),
                        min(10000., size*radius*.05), None, SOURCE,
                        'Prescribed inherited structure; no constitutive weakening or active slip assigned.'))
                case = GeologicalCase('seeded-initial-lithosphere', GeologicalDomain(sphere, SOURCE),
                    time_s=now, epoch_id=inputs['epoch']['id'], depth_reference_id=inputs['frame']['vertical_reference'],
                    source_id=SOURCE, sources=(source, *references), materials=materials, cohorts=tuple(cohorts),
                    thermal_profiles=tuple(profiles), columns=tuple(columns), geometries=tuple(geometries),
                    provinces=tuple(provinces), weak_zones=tuple(zones),
                    precedence=FeaturePrecedence(tuple(p.province_id for p in provinces[1:])+('background',)), budget=budget)
                state = PrecursorState(case, origins=tuple(InputOrigin(s.source_id, 'authored',
                    METHOD if s.source_id == SOURCE else 'Earth reference catalogue') for s in case.sources),
                    cooling_history=tuple(cooling), library=library, budget=budget)
                realised = math.fsum(g.area_steradians for _, g, *_ in footprints)/(4*math.pi)
                realised = realised if f <= .5 else 1-realised
                if abs(realised-f) > 2e-11:
                    _fail('Continental surface fraction failed its native geometry account.')
                report = dict(schema=METHOD, status='WORKING NON-CANON', inputs=inputs,
                    binding=binding, execution_id=context.identity, state_id=state.state_id,
                    case_id=case.definition_id, realised_continental_fraction=realised,
                    columns=details, feature_geometry_ids={g.key: g.geometry.geometry_id for g in geometries},
                    scientific_status='DECLARED_INITIAL_CONDITION_SCENARIO',
                    max_planar_depth_radius_ratio=max(c.lithosphere_thickness_m for c in columns)/radius,
                    assumptions=statement, references=list(REFERENCES))
                check()
                if _source_binding() != binding:
                    raise ContractError('SOURCE_MISMATCH', 'Initial-structure dependencies changed.')
                context.verify()
                return WorldStructure(state, report)
    except MemoryLimitError as exc:
        raise ContractError('MEMORY_LIMIT', 'Initial structure exceeds the requested work budget.') from exc


def check_structure(plan, structure, *, current=False):
    from atlas_tectonics import PrecursorState
    if type(structure) is not WorldStructure or type(structure.state) is not PrecursorState:
        _fail('A native precursor and initial-structure receipt are required.')
    r, s = structure.report, structure.state
    if (r.get('schema') != METHOD or r.get('status') != 'WORKING NON-CANON'
            or r.get('inputs') != _inputs(plan) or r.get('state_id') != s.state_id
            or r.get('case_id') != s.case.definition_id
            or r.get('feature_geometry_ids') != {g.key:g.geometry.geometry_id for g in s.case.geometries}):
        _fail('Initial structure, configuration and saved native state disagree.')
    sources = {x.source_id: x for x in s.case.sources}
    if sources[SOURCE].content_sha256 != _hash(dict(inputs=r['inputs'], binding=r['binding'], method=METHOD)):
        _fail('Initial structure source binding differs from its retained input recipe.')
    if current:
        from atlas_tectonics.reuse import ExecutionContext
        if r['binding'] != _source_binding():
            raise ContractError('SOURCE_MISMATCH', 'Initial-structure source changed; no silent rebind.')
        with ExecutionContext() as context:
            if context.identity != r['execution_id']:
                raise ContractError('SOURCE_MISMATCH', 'Native initial-structure runtime/source changed.')
            context.verify()


def save_structure(structure, store):
    """Store one native precursor and one compact receipt, using existing Zstd."""
    import numpy as np
    from atlas_tectonics import save_precursor_state
    save_precursor_state(structure.state, store)
    store.put(structure.structure_id, {'receipt': np.frombuffer(canonical_bytes(structure.report), dtype='u1')},
              dict(schema=METHOD, state_id=structure.state.state_id))
    return structure.structure_id


def load_structure(store, structure_id):
    import numpy as np
    from atlas_tectonics import load_precursor_state
    arrays, metadata = store.get(structure_id), store.metadata(structure_id)
    if (type(arrays) is not dict or set(arrays) != {'receipt'} or type(metadata) is not dict
            or set(metadata) != {'schema', 'state_id'} or metadata['schema'] != METHOD):
        _fail('Missing or invalid initial-structure receipt.')
    a = arrays['receipt']
    if a.dtype != np.dtype('u1') or a.ndim != 1 or a.nbytes > 65536:
        _fail('Invalid initial-structure receipt payload.')
    report = parse_json(a.tobytes())
    if _hash(report) != structure_id or report.get('state_id') != metadata['state_id']:
        _fail('Initial-structure receipt identity mismatch.')
    state = load_precursor_state(store, metadata['state_id'])
    if state is None:
        _fail('Native precursor dependency is missing.')
    return WorldStructure(state, report)


def structure_view(structure):
    """Actual geological feature geometry and shared column profiles for the UI.

    Feature rings are original minor-arc directions, not a raster classified at
    patch centres. UI owns rendering only. Native sampling owns mixed-cell means.
    """
    import numpy as np
    s = structure.state
    details = {d['column_id']: d for d in structure.report['columns']}
    geometry = []
    for item in s.case.geometries:
        g = item.geometry
        shape = g._projected._geom
        xy = shape.exterior.coords if shape.geom_type == 'Polygon' else shape.coords
        geometry.append(dict(id=item.key, kind=shape.geom_type,
            directions=g.chart._unproject(np.asarray(xy)).tolist()))
    return dict(schema='atlas.initial-structure-view.v1', structure_id=structure.structure_id,
        state_id=s.state_id, frame_id=s.case.topology.frame_id, epoch_id=s.case.epoch_id,
        time_s=s.case.time_s, depth_reference_id=s.case.depth_reference_id,
        continental_fraction=structure.report['realised_continental_fraction'],
        status=structure.report['scientific_status'], assumptions=structure.report['assumptions'],
        columns=[dict(column_id=c.column_id, crust_type=c.crust_type,
            thermal_profile_id=c.thermal_profile_id,
            crust_thickness_m=c.crust_thickness_m, lithosphere_thickness_m=c.lithosphere_thickness_m,
            layers=[dict(layer_id=l.layer_id, role=l.role, thickness_m=l.bulk_thickness_m,
                material_ids=[next(x.cohort.material_id for x in s.case.cohorts if x.cohort.cohort_id == p.cohort_id)
                              for p in l.components]) for l in c.layers],
            **{k:v for k,v in details[c.column_id].items() if k not in ('column_id','crust_type')}) for c in s.case.columns],
        provinces=[dict(province_id=p.province_id, column_id=p.column_id,
                        selector=dict(kind=p.selector.kind, keys=list(p.selector.keys))) for p in s.case.provinces],
        precedence=list(s.case.precedence.province_order), features=geometry,
        thermal_profiles=[dict(profile_id=t.profile_id, depths_m=list(t.depths_m), temperatures_k=list(t.temperatures_k))
                          for t in s.case.thermal_profiles],
        weak_zones=[dict(zone_id=z.zone_id, geometry_ids=list(z.selector.keys), top_depth_m=z.top_depth_m,
                        bottom_depth_m=z.bottom_depth_m, half_width_m=z.half_width_m,
                        strength_factor=z.strength_factor, unknown_reason=z.unknown_reason) for z in s.case.weak_zones],
        references=list(REFERENCES))
