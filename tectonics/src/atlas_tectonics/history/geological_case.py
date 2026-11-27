"""W01 stage 4: validated, immutable geological descriptions on stage-3 geometry.

No sampling grid, transport step, force calculation or thermal evolution occurs.
Catalogues refer to shared records by stable IDs; geometry is stored once, not
copied into every province/fault/zone. Priorities are explicit and resolution of
candidate IDs is deterministic. Geometry membership itself remains stage 5.

Persistence uses ONE existing ArrayStore snapshot with all decoding dependencies:
source records, columns, geometry, topology and its generation provenance. Missing
or corrupt dependencies are errors, never a reason to regenerate a random world.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict, is_dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any

import numpy as np

from atlas_tectonics.history.geological_records import (GeologyError, GeologySource, MaterialDefinition,
    CohortDescription, ThermalInitialProfile, LayerComponent, GeologicalLayer,
    ColumnDescription, SurfaceSelector, GeologicalProvince, FaultDescription,
    WeakZoneDescription, FeaturePrecedence, _name, _names)
from atlas_tectonics.materials.materials import MaterialCohort
from atlas_tectonics._validation import scalar, TectonicsError
from atlas_tectonics.planet.geometry import PlanarGeometry, GeometryLimits, _limits, _check_cancel
from atlas_tectonics.planet.spherical_geometry import SphericalGeometry, SphericalChart
from atlas_tectonics.planet.spherical_atlas import SphericalAtlas, _restore_atlas
from atlas_tectonics.plates.boundaries import BoundaryNetwork, BoundaryRegion, build_boundary_network
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import _immutable_deepcopy
from atlas_tectonics.history.geological_domain import GeologicalDomain, restore_geological_domain

_SCHEMA = 'atlas.geological-case.v1'
_BUNDLE = 'atlas.geological-case-snapshot.v1'
_PROPERTY_NAMES = ('density_kg_m3', 'conductivity_w_m_k', 'specific_heat_j_kg_k',
                   'heat_production_w_m3', 'thermal_expansion_per_k', 'reference_temperature_k')


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise GeologyError('description requires finite JSON data') from exc


def _sha(text):
    return text


@dataclass(frozen=True, slots=True)
class GeologyLimits:
    """Finite description/import limits, not physical constants or an RSS cap."""
    max_records: int = 20_000
    max_profile_points: int = 100_000
    max_definition_bytes: int = 4*1024**2
    max_geometry_bytes: int = 64*1024**2

    def __post_init__(self):
        for name in ('max_records','max_profile_points','max_definition_bytes','max_geometry_bytes'):
            if type(getattr(self,name)) is not int or getattr(self,name) <= 0:
                raise GeologyError(name+' must be a positive integer')


def _case_limits(value):
    if value is None: return GeologyLimits()
    return value


@dataclass(frozen=True, slots=True)
class FeatureGeometry:
    """Named immutable geometry, reusable by several geological descriptions."""
    key: str
    geometry: PlanarGeometry | SphericalGeometry
    source_id: str

    def __post_init__(self):
        _name(self.key,'geometry key'); _name(self.source_id,'geometry source')
        if type(self.geometry) not in (PlanarGeometry, SphericalGeometry) or self.geometry.is_empty:
            raise GeologyError('nonempty supported feature geometry required')
        if self.geometry.kind not in ('Polygon','MultiPolygon','LineString','MultiLineString'):
            raise GeologyError('only pure area or line feature geometry is supported')


@dataclass(frozen=True, slots=True)
class ProvinceResolution:
    """Selection receipt retaining all declared matches, not a point-membership test."""
    province_id: str
    column_id: str
    matching_province_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnresolvedGeology:
    path: str
    reason: str


def _catalogue(values, cls, label, key, limit):
    [key(x) for x in values]
    return tuple(sorted(values,key=key))


def _record_text_bytes(value):
    """Bound string-copy cost before canonicalisation, without expanding geometry."""
    if type(value) is str: return len(value.encode('utf-8'))
    if type(value) is tuple: return sum(_record_text_bytes(v) for v in value)
    if is_dataclass(value):
        return sum(_record_text_bytes(getattr(value,f.name)) for f in fields(value)
                   if not (type(value) is FeatureGeometry and f.name == 'geometry'))
    return 0


def _topology_id(topology):
    if type(topology) is BoundaryNetwork: return topology.network_id
    if type(topology) is SphericalAtlas: return topology.atlas_id
    if type(topology) is GeologicalDomain: return topology.domain_id
    raise GeologyError('validated BoundaryNetwork, SphericalAtlas or GeologicalDomain required')


def _check_geometry_frame(topology, geometry, geometry_limits, budget):
    if type(topology) is SphericalAtlas or (type(topology) is GeologicalDomain and topology.full_sphere):
        return  # Every valid patch on the same sphere lies in the planetary domain.
    domain = topology.domain
    if type(domain) is PlanarGeometry:
        pass
    else:
        geometry.in_chart(domain.chart, limits=geometry_limits, budget=budget)


@dataclass(frozen=True, slots=True, init=False)
class GeologicalCase:
    """One initial geological definition, independent of a sampling mesh.

    Exactly one explicitly supplied whole-domain background supplies coverage. It
    may itself declare unknown properties. Higher-priority provinces replace a
    whole column only where stage 5 finds their membership. This avoids treating
    patch/plate IDs as crust classifications or inventing material in a gap.

    Record order is canonicalised except where it has physical meaning: layer
    order, profile samples and precedence. The owner accounts retained objects;
    construction uses the shared budget and never creates a new worker/cache pool.
    """
    case_id: str
    topology: BoundaryNetwork | SphericalAtlas | GeologicalDomain
    time_s: float
    epoch_id: str
    depth_reference_id: str
    source_id: str
    sources: tuple[GeologySource, ...]
    materials: tuple[MaterialDefinition, ...]
    cohorts: tuple[CohortDescription, ...]
    thermal_profiles: tuple[ThermalInitialProfile, ...]
    columns: tuple[ColumnDescription, ...]
    geometries: tuple[FeatureGeometry, ...]
    provinces: tuple[GeologicalProvince, ...]
    faults: tuple[FaultDescription, ...]
    weak_zones: tuple[WeakZoneDescription, ...]
    precedence: FeaturePrecedence
    definition_id: str
    _definition: bytes = field(repr=False,compare=False)
    _lookups: Any = field(repr=False,compare=False)
    _issues: tuple[UnresolvedGeology, ...] = field(repr=False,compare=False)
    _province_rank: Any = field(repr=False,compare=False)
    _zone_rank: Any = field(repr=False,compare=False)

    def __init__(self, case_id, topology, *, time_s, epoch_id, depth_reference_id,
                 source_id, sources, materials, cohorts, thermal_profiles, columns,
                 provinces, precedence, geometries=(), faults=(), weak_zones=(),
                 limits=None, geometry_limits=None, budget=None, cancel=None):
        _check_cancel(cancel)
        limits = _case_limits(limits); _limits(geometry_limits)
        tid = _topology_id(topology)
        for value,label in ((case_id,'case_id'),(epoch_id,'epoch_id'),
                            (depth_reference_id,'depth_reference_id'),(source_id,'source_id')):
            _name(value,label)
        time_s = scalar(time_s,'case time')
        specs = (('sources',sources,GeologySource,lambda x:x.source_id),
                 ('materials',materials,MaterialDefinition,lambda x:x.material_id),
                 ('cohorts',cohorts,CohortDescription,lambda x:x.cohort.cohort_id),
                 ('thermal_profiles',thermal_profiles,ThermalInitialProfile,lambda x:x.profile_id),
                 ('columns',columns,ColumnDescription,lambda x:x.column_id),
                 ('geometries',geometries,FeatureGeometry,lambda x:x.key),
                 ('provinces',provinces,GeologicalProvince,lambda x:x.province_id),
                 ('faults',faults,FaultDescription,lambda x:x.fault_id),
                 ('weak_zones',weak_zones,WeakZoneDescription,lambda x:x.zone_id))
        # Count before making maps or serialising. Nested records are charged too.
        count = sum(len(x[1]) for x in specs)
        for c in columns:
            count += len(c.layers) + sum(len(x.components) for x in c.layers)
        points = sum(len(p.depths_m)+len(p.temperatures_k) for p in thermal_profiles
                     if type(p) is ThermalInitialProfile)
        # Include retained source strings in preflight; bounded strings live in
        # records, but their total must not be omitted from conversion workspace.
        text_bytes = sum(_record_text_bytes(values) for _,values,_,_ in specs)
        estimate = 8192*count + 128*points + 8*text_bytes + 65536
        with select_budget(budget).reserve(estimate,category='geological-case'):
            catalogues = {}; maps = {}
            for name,values,cls,key in specs:
                ordered = _catalogue(values,cls,name,key,limits.max_records)
                catalogues[name] = ordered; maps[name] = {key(x):x for x in ordered}
            def ref(table, key):
                return maps[table][key]
            ref('sources',source_id)
            if type(topology) is GeologicalDomain:
                ref('sources',topology.source_id)
            for name,values in catalogues.items():
                if name != 'sources':
                    for value in values: ref('sources',value.source_id)
            for c in catalogues['cohorts']:
                if ref('materials',c.cohort.material_id).material_class != 'solid':
                    raise GeologyError('W02 geological cohorts must describe solids, not pore fluid')
                if c.cohort.formation_time_s is not None and c.cohort.formation_time_s > time_s:
                    raise GeologyError('material formation lies after case time')
            for p in catalogues['thermal_profiles']:
                if p.cooling_start_time_s is not None:
                    pass
            for c in catalogues['columns']:
                for layer in c.layers:
                    ref('sources',layer.source_id)
                    for component in layer.components:
                        ref('cohorts',component.cohort_id).cohort
            unique_geometries = {g.geometry.geometry_id:g.geometry for g in catalogues['geometries']}
            stored_geometries = dict(unique_geometries)
            if type(topology) is BoundaryNetwork or (type(topology) is GeologicalDomain and not topology.full_sphere):
                for g in (topology.domain, *(r.geometry for r in topology.regions)):
                    stored_geometries[g.geometry_id] = g
            geometry_bytes = sum(len(g.wkb if type(g) is PlanarGeometry else g._projected.wkb) for g in stored_geometries.values())
            if type(topology) is SphericalAtlas:
                geometry_bytes += topology.vertex_directions.nbytes
            for geometry in unique_geometries.values():
                _check_cancel(cancel)
            def selector(s, *, area=False, half_width=None):
                kinds = set()
                if s.kind == 'geometry':
                    for key in s.keys:
                        kinds.add(ref('geometries',key).geometry.kind)
            for province in catalogues['provinces']:
                ref('columns',province.column_id); selector(province.selector,area=True)
            for fault in catalogues['faults']:
                for key in fault.trace_keys:
                    if ref('geometries',key).geometry.kind not in ('LineString','MultiLineString'):
                        raise GeologyError('fault description requires directed line geometry')
            for zone in catalogues['weak_zones']:
                selector(zone.selector,half_width=zone.half_width_m)
            data = {'schema':_SCHEMA,'case_id':case_id,'topology_kind': ('pre-partition' if type(topology) is GeologicalDomain else 'sphere' if type(topology) is SphericalAtlas else 'regional'),
                'topology_id':tid,'time_s':time_s,'epoch_id':epoch_id,'depth_reference_id':depth_reference_id,
                'source_id':source_id,'precedence':asdict(precedence)}
            for name,values in catalogues.items():
                data[name] = ([{'key':v.key,'source_id':v.source_id,'geometry_id':v.geometry.geometry_id} for v in values]
                              if name == 'geometries' else [asdict(v) for v in values])
            definition = _json(data)
            for key,value in dict(case_id=case_id,topology=topology,time_s=time_s,epoch_id=epoch_id,
                                  depth_reference_id=depth_reference_id,source_id=source_id,precedence=precedence,**catalogues).items():
                object.__setattr__(self,key,value)
            object.__setattr__(self,'_definition',definition)
            object.__setattr__(self,'definition_id',hashlib.sha256(definition).hexdigest())
            object.__setattr__(self,'_lookups',MappingProxyType({k:MappingProxyType(v) for k,v in maps.items()}))
            object.__setattr__(self,'_issues',self._find_unknowns())
            object.__setattr__(self,'_province_rank',MappingProxyType({k:i for i,k in enumerate(precedence.province_order)}))
            object.__setattr__(self,'_zone_rank',MappingProxyType({k:i for i,k in enumerate(precedence.weak_zone_order)}))
            _check_cancel(cancel)

    def descriptor(self):
        """Detached metadata; editing it cannot change this accepted definition."""
        return json.loads(self._definition)

    @property
    def definition_bytes(self): return len(self._definition)

    @property
    def retained_bytes_estimate(self):
        """Case-owned metadata estimate; topology and feature geometry are shared owners."""
        return len(self._definition)+1024*sum(len(v) for v in self._lookups.values())+65536

    @property
    def unresolved(self): return self._issues

    def _find_unknowns(self):
        issues = []
        for m in self.materials:
            for key in _PROPERTY_NAMES:
                if getattr(m,key) is None: issues.append(UnresolvedGeology('materials/'+m.material_id+'/'+key,m.unknown_reason))
        for c in self.cohorts:
            if c.cohort.formation_time_s is None:
                issues.append(UnresolvedGeology('cohorts/'+c.cohort.cohort_id+'/formation_time_s','explicitly unknown formation time'))
        for p in self.thermal_profiles:
            if p.mode == 'unknown': issues.append(UnresolvedGeology('thermal_profiles/'+p.profile_id,p.unknown_reason))
        for c in self.columns:
            if c.crust_type == 'unknown': issues.append(UnresolvedGeology('columns/'+c.column_id+'/crust_type','explicitly unknown crust classification'))
            for l in c.layers:
                if l.porosity is None: issues.append(UnresolvedGeology('columns/'+c.column_id+'/'+l.layer_id+'/porosity',l.unknown_porosity_reason))
        for z in self.weak_zones:
            if z.strength_factor is None: issues.append(UnresolvedGeology('weak_zones/'+z.zone_id+'/strength_factor',z.unknown_reason))
        return tuple(issues)

    def column(self, column_id):
        _name(column_id,'column ID')
        try: return self._lookups['columns'][column_id]
        except KeyError as exc: raise GeologyError('unknown column ID') from exc

    def resolve_provinces(self, matching_ids):
        """Resolve already computed in-domain matches; DOES NOT query coordinates.

        The explicit whole-domain background is always a candidate. All matches
        are retained in precedence order, so a future boundary/mixed-cell sampler
        cannot mistake this single winner for an integrated cell composition.
        """
        _names(matching_ids,'candidate provinces')
        candidates = set(matching_ids) | {self.precedence.province_order[-1]}
        # O(k log k) in actual candidates, not a scan of every world province.
        ordered = tuple(sorted(candidates,key=self._province_rank.__getitem__))
        p = self._lookups['provinces'][ordered[0]]
        return ProvinceResolution(p.province_id,p.column_id,ordered)

    def resolve_weak_zones(self, matching_ids):
        """No implicit multiplication/addition of overlapping strength factors."""
        _names(matching_ids,'candidate weak zones')
        if self.precedence.weak_zone_mode == 'retain_all': return tuple(sorted(matching_ids))
        return () if not matching_ids else (min(matching_ids,key=self._zone_rank.__getitem__),)

    __deepcopy__ = _immutable_deepcopy

    def __reduce__(self):
        meta,arrays = _snapshot(self)
        return (restore_geological_case,(meta,{k:(v.dtype.str,v.shape,v.tobytes()) for k,v in arrays.items()},self.definition_id))


def _snapshot(case):
    """Self-contained snapshot, sharing identical geometry payloads by identity."""
    geometries = {x.geometry.geometry_id:x.geometry for x in case.geometries}
    # The canonical definition itself is a chunked/compressed byte dataset. Large
    # shared profile tables therefore do not inflate uncompressed store metadata.
    arrays = {'definition': np.frombuffer(case._definition,dtype='u1')}
    topology = case.topology
    td = topology.descriptor()
    if type(topology) is SphericalAtlas:
        arrays['topology_directions'] = topology.vertex_directions
    elif not (type(topology) is GeologicalDomain and topology.full_sphere):
        for g in (topology.domain,*(r.geometry for r in topology.regions)):
            geometries[g.geometry_id] = g
    gd = {}
    for i,(key,g) in enumerate(sorted(geometries.items())):
        name = 'geometry_'+str(i)
        arrays[name] = np.frombuffer(g.wkb if type(g) is PlanarGeometry else g._projected.wkb,dtype='u1')
        gd[key] = {'array':name,'descriptor':g.descriptor()}
    return {'schema':_BUNDLE,'definition_id':case.definition_id,'topology':td,'geometries':gd}, arrays


def restore_geological_case(metadata, arrays, expected_id, *, limits=None, geometry_limits=None, budget=None, cancel=None):
    """Validate metadata, rebuild native geometry and recheck the complete case ID.

    ``arrays`` can be ArrayStore immutable arrays or typed bytes from __reduce__.
    This function never runs code supplied in metadata. Limits precede native
    geometry reconstruction; stored derived indexes are not accepted.
    """
    _check_cancel(cancel)
    limits = _case_limits(limits); gl = _limits(geometry_limits)
    raw_value = arrays['definition']
    if type(raw_value) is tuple:
        raw = raw_value[2]
    elif type(raw_value) is np.ndarray and raw_value.dtype == np.dtype('u1') and raw_value.ndim == 1:
        raw = raw_value.tobytes()
    else: raise GeologyError('definition must be a one-dimensional uint8 dataset')
    try:
        d = json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise GeologyError('invalid geological definition JSON') from exc
    for name in ('sources','materials','cohorts','thermal_profiles','columns','geometries','provinces','faults','weak_zones'):
        d.get(name)
    record_count = sum(len(d[name]) for name in ('sources','materials','cohorts','thermal_profiles','columns','geometries','provinces','faults','weak_zones'))
    for row in d['columns']:
        layers = row.get('layers')
        record_count += len(layers)
        for l in layers: record_count += len(l.get('components'))
    points = 0
    for row in d['thermal_profiles']:
        for key in ('depths_m','temperatures_k'):
            values = row.get(key)
            points += len(values)
    expected_arrays = {'definition'}
    for row in metadata['geometries'].values():
        expected_arrays.add(row['array'])
    if d.get('topology_kind') == 'sphere': expected_arrays.add('topology_directions')
    elif d.get('topology_kind') not in ('regional','pre-partition'): raise GeologyError('unsupported topology kind')
    # Decode typed bytes without trusting shape arithmetic or mutable array flags.
    views = {}
    total = 0
    for key,value in arrays.items():
        if key == 'definition': continue
        _check_cancel(cancel)
        if type(value) is tuple:
            dtype,shape,payload = value
            a = np.frombuffer(payload,dtype=dtype).reshape(shape)
        elif type(value) is np.ndarray:
            a = value
        else: raise GeologyError('unsupported geometry array')
        if key == 'topology_directions':
            if a.dtype != np.dtype('f8') or a.ndim != 2 or a.shape[1] != 3: raise GeologyError('invalid atlas directions')
        elif a.dtype != np.dtype('u1') or a.ndim != 1: raise GeologyError('invalid WKB array')
        total += a.nbytes; views[key] = a
    with select_budget(budget).reserve(8*len(raw)+4*total+4096*record_count+65536,category='geological-restore'):
        try:
            geometry = {}
            for key,row in metadata['geometries'].items():
                _check_cancel(cancel)
                if set(row) != {'array','descriptor'}: raise GeologyError('invalid geometry row')
                desc = row['descriptor']; payload = views[row['array']].tobytes()
                if desc['space'] == 'planar-metres':
                    g = PlanarGeometry.from_wkb(payload,frame_id=desc['frame_id'],limits=gl,budget=budget)
                elif desc['space'] == 'sphere-minor-arcs':
                    g = SphericalGeometry.from_projected_wkb(payload,chart=SphericalChart.from_descriptor(desc['chart']),limits=gl,budget=budget)
                else: raise GeologyError('unsupported stored geometry space')
                if g.geometry_id != key or g.descriptor() != desc: raise GeologyError('geometry identity mismatch')
                geometry[key] = g
            td = metadata['topology']
            if d['topology_kind'] == 'sphere':
                topology = _restore_atlas(td,views['topology_directions'].tobytes(),limits=gl,budget=budget,cancel=cancel)
            elif d['topology_kind'] == 'pre-partition':
                topology = restore_geological_domain(td,geometry)
            else:
                domain = geometry[td['domain']['geometry_id']]
                regions = tuple(BoundaryRegion(r['region_id'],r['plate_id'],geometry[r['geometry']['geometry_id']]) for r in td['regions'])
                topology = build_boundary_network(domain,regions,limits=gl,budget=budget,cancel=cancel)
            if topology.descriptor() != td or _topology_id(topology) != d['topology_id']:
                raise GeologyError('stored case/topology identity mismatch')
            kwargs = _restore_records(d,geometry)
            result = GeologicalCase(d['case_id'],topology,time_s=d['time_s'],epoch_id=d['epoch_id'],
                depth_reference_id=d['depth_reference_id'],source_id=d['source_id'],
                **kwargs,limits=limits,geometry_limits=gl,budget=budget,cancel=cancel)
            if result.definition_id != expected_id or result.descriptor() != d:
                raise GeologyError('restored geological definition mismatch')
            if _snapshot(result)[0] != metadata:
                raise GeologyError('unused or inconsistent snapshot dependencies')
            return result
        except (KeyError,TypeError,ValueError,OverflowError) as exc:
            if isinstance(exc,TectonicsError): raise
            raise GeologyError('malformed geological snapshot') from exc


def _restore_records(d, geometry):
    def record(cls,row,**changes): return cls(**dict(row,**changes))
    sources = tuple(record(GeologySource,r,references=tuple(r['references'])) for r in d['sources'])
    materials = tuple(record(MaterialDefinition,r,valid_temperature_k=None if r['valid_temperature_k'] is None else tuple(r['valid_temperature_k'])) for r in d['materials'])
    cohorts = tuple(CohortDescription(MaterialCohort(**r['cohort']),r['source_id']) for r in d['cohorts'])
    thermal = tuple(record(ThermalInitialProfile,r,depths_m=tuple(r['depths_m']),temperatures_k=tuple(r['temperatures_k'])) for r in d['thermal_profiles'])
    columns = []
    for r in d['columns']:
        layers = tuple(record(GeologicalLayer,l,components=tuple(LayerComponent(**c) for c in l['components'])) for l in r['layers'])
        columns.append(record(ColumnDescription,r,layers=layers))
    def selector(r): return record(SurfaceSelector,r,keys=tuple(r['keys']))
    return dict(sources=sources,materials=materials,cohorts=cohorts,thermal_profiles=thermal,columns=tuple(columns),
        geometries=tuple(FeatureGeometry(r['key'],geometry[r['geometry_id']],r['source_id']) for r in d['geometries']),
        provinces=tuple(record(GeologicalProvince,r,selector=selector(r['selector'])) for r in d['provinces']),
        faults=tuple(record(FaultDescription,r,trace_keys=tuple(r['trace_keys'])) for r in d['faults']),
        weak_zones=tuple(record(WeakZoneDescription,r,selector=selector(r['selector'])) for r in d['weak_zones']),
        precedence=record(FeaturePrecedence,d['precedence'],province_order=tuple(d['precedence']['province_order']),
                          weak_zone_order=tuple(d['precedence']['weak_zone_order'])))


def save_geological_case(case, store, *, budget=None, cancel=None):
    """One transactional, self-contained definition; no new persistence service."""
    _check_cancel(cancel)
    policy = store._budget if budget is None else budget
    # The topology descriptor also allocates Python lists/maps. Include it and
    # generation provenance; definition bytes alone would undercount a large atlas.
    topology = case.topology
    topo_work = 2048*(topology.vertex_count + topology.edge_count + len(topology.regions))
    topo_work += 8*len(getattr(topology,'_provenance',b''))
    with select_budget(policy).reserve(8*case.definition_bytes+topo_work+65536,category='geological-save'):
        metadata,arrays = _snapshot(case)
        return store.put(case.definition_id,arrays,metadata,budget=policy,cancel=cancel)


def load_geological_case(store, definition_id, *, limits=None, geometry_limits=None, budget=None, cancel=None):
    _check_cancel(cancel)
    policy = store._budget if budget is None else budget
    arrays = store.get(definition_id,budget=policy)
    if arrays is None: return None
    return restore_geological_case(store.metadata(definition_id),arrays,definition_id,
        limits=limits,geometry_limits=geometry_limits,budget=policy,cancel=cancel)
