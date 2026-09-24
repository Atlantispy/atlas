"""Bounded lossless records for supplied tectonic histories, not live plans.

The history owner must check expected execution, producer inputs and dates.
Content hashes establish internal integrity, not provenance or physical acceptance.
Returned immutable results/arrays have caller-owned storage after this operation.
"""
from __future__ import annotations

import math

import numpy as np

from ._validation import TectonicsError, scalar
from .constitutive import _cancel
from .evolving_flexure import EvolvingW04SupportResult
from .evolving_mechanics import EvolvingMechanicalResult, RegionalInputContext
from .geometry import PlanarGeometry, DEFAULT_GEOMETRY_LIMITS, _label
from .materials import MaterialCohort
from .regional_checkpoint import (pack_regional_snapshots, restore_regional_snapshots,
    _json, _parse, _keys, _sha, _hash)
from .regional_execution import RegionalMechanicalSnapshot
from .resources import WorkBudget, MemoryLimitError, select_budget
from .regional_stokes import boundary_coordinates
from .underthrust import UnderthrustState, UnderthrustInterface, MAX_PARCELS, MAX_RECEIVERS, _id as _under_id
from .w04_workflow import _id as _w04_id


CAP = 128 << 20
SCHEMA = 'atlas.tectonic-history-result.v1'
_KINDS = {UnderthrustState: 'underthrust', EvolvingW04SupportResult: 'evolving-w04',
          EvolvingMechanicalResult: 'evolving-regional'}
_META = {'schema', 'kind', 'result_id', 'descriptor', 'regional', 'arrays', 'resources', 'content_id'}
_UNDER_KEYS = set(('plan_id execution_id time_s frame_id datum_id epoch_id interface parcels '
    'current_geometry_ids destination_ids enthalpy_known host_space_source_id boundary_work '
    'energy_residual_not_assigned_to_heat exterior geometric_area_error_m2').split())
_W04_KEYS = set(('schema plan_id reference_state current_state reference_surface current_surface '
    'reference_time_s time_s reference_rigidity current_rigidity reference_profile current_profile '
    'reference_operator current_operator absolute_reference_load reference_exterior current_exterior '
    'source_workflow epoch_id depth_reference_id execution_id thermal_owner vertical_response_owner '
    'w03_local_displacement total_reference_result surface_change_semantics feedback_applied policy '
    'response accuracy absolute_current_maxima mesh_change_estimate reference_subdivisions '
    'current_subdivisions exterior_uncertainty validity').split())
_REGIONAL_KEYS = set(('schema request input_blocks surface_pressure mechanical_result_id '
    'steady_snapshot time_advanced response_owner displacement_added origin_x_m origin_z_m coordinates').split())


def _fail(message):
    raise TectonicsError('tectonic history codec '+message)


def _kind(out):
    if type(out) not in _KINDS:
        _fail('requires an exact supported result type')
    return _KINDS[type(out)]


def history_result_id(out):
    """Return the existing scientific identity, never an envelope identity."""
    return _sha(out.state_id if _kind(out) == 'underthrust' else out.result_id)


def history_result_nbytes(out):
    """Conservative retained allowance including geometry/native object headroom.

    This is byte admission, not measured process RSS. It deliberately exceeds
    the producer's definition-only geometry count and W04's raw payload size.
    """
    kind = _kind(out)
    if kind == 'underthrust':
        size = out.nbytes + 4*len(out._record) + sum(
            2048*p.vertex_count+8192 for p in out.polygons) + 1024*len(out.parcel_ids)
    elif kind == 'evolving-w04':
        size = len(out._payload)+len(out._wet)+len(out._absolute)+5*len(out._metadata)+4096
    else:
        size = out.nbytes+4*(len(out._record)+len(out.mechanics._metadata))+8192*len(out.array_names)
    if size > CAP:
        _fail('retained result exceeds 128 MiB')
    return size


def _record(out):
    raw = out._metadata if type(out) is EvolvingW04SupportResult else out._record
    if type(raw) is not bytes or len(raw) > 512*1024:
        _fail('bounded immutable descriptor required')
    return _parse(raw)


def _view(raw, dtype, shape):
    if type(raw) is not bytes or len(raw) != math.prod(shape)*np.dtype(dtype).itemsize:
        _fail('immutable field bytes do not match shape')
    return np.frombuffer(raw, dtype=dtype).reshape(shape)


def _under_arrays(out, d):
    _keys(d, _UNDER_KEYS, 'underthrust descriptor')
    n, r = len(out.parcel_ids), len(out.destination_ids)
    if (type(out.polygons) is not tuple or type(out.parcel_ids) is not tuple or
            type(out.destination_ids) is not tuple or type(out.enthalpy_known) is not tuple or
            not 2 <= n <= MAX_PARCELS or not 1 <= r <= MAX_RECEIVERS+1 or len(out.polygons) != n or
            len(out.enthalpy_known) != n or any(type(x) is not bool for x in out.enthalpy_known)):
        _fail('invalid underthrust coverage')
    for ids in (out.parcel_ids, out.destination_ids):
        if len(set(ids)) != len(ids): _fail('duplicate underthrust labels')
        for key in ids: _label(key, 'history label')
    if (len(d['parcels']) != n or len(d['geometric_area_error_m2']) != n or
            d['destination_ids'] != list(out.destination_ids) or
            d['enthalpy_known'] != list(out.enthalpy_known) or d['time_s'] != out.time_s or
            d['plan_id'] != out.plan_id or d['boundary_work'] != 'supplied-generalised-force-times-horizontal-slip' or
            d['energy_residual_not_assigned_to_heat'] is not True or
            d['exterior'] != 'retained-material-not-a-second-export'):
        _fail('underthrust descriptor/state mismatch')
    scalar(out.time_s, 'history time'); _sha(out.plan_id); _sha(d['execution_id'])
    for key in ('frame_id', 'datum_id', 'epoch_id', 'host_space_source_id'):
        _label(d[key], key)
    interface = dict(d['interface'])
    if (interface.pop('axes', None) != 'x-downdip,z-up' or
            interface.pop('endpoint_extension', None) != 'supplied-horizontal-flats'):
        _fail('underthrust interface convention mismatch')
    fault = UnderthrustInterface(**interface)
    if fault.frame_id != d['frame_id'] or fault.datum_id != d['datum_id']:
        _fail('underthrust interface frame/datum mismatch')
    arrays = dict(fields=_view(out._fields, 'float64', (3,n,r)),
        work=_view(out._work, 'float64', (2,)), potential=_view(out._potential, 'float64', (n,)),
        displacement=_view(out._displacement, 'float64', (2,)))
    f = arrays['fields']
    if np.any(f[:2] < 0): _fail('negative volume/mass')
    current_ids, vertices = [], 0
    for i, (p, row) in enumerate(zip(out.polygons, d['parcels'])):
        _keys(row, {'parcel_id','block_id','role','cohort','geometry_id','density_kg_m3',
                    'specific_enthalpy_j_kg','enthalpy_source_id'}, 'underthrust parcel')
        if (type(p) is not PlanarGeometry or p.frame_id != d['frame_id'] or p.is_empty or
                p.kind not in ('Polygon','MultiPolygon') or p.area_m2 <= 0 or row['parcel_id'] != out.parcel_ids[i] or
                row['role'] not in ('footwall','hangingwall','host')):
            _fail('invalid occupied underthrust geometry/parcel')
        _label(row['block_id'], 'block'); _sha(row['geometry_id']); MaterialCohort(**row['cohort'])
        density = scalar(row['density_kg_m3'], 'density', positive=True)
        heat = row['specific_enthalpy_j_kg']
        if out.enthalpy_known[i] != (heat is not None): _fail('enthalpy known mask mismatch')
        if heat is None:
            if row['enthalpy_source_id'] is not None or np.any(f[2,i] != 0):
                _fail('unknown enthalpy must remain masked placeholder')
        else:
            scalar(heat, 'specific enthalpy'); _label(row['enthalpy_source_id'], 'enthalpy source')
            if not np.allclose(f[2,i], f[1,i]*heat, rtol=256*np.finfo(float).eps, atol=0):
                _fail('signed enthalpy does not match parcel mass')
        if not np.allclose(f[1,i], f[0,i]*density, rtol=256*np.finfo(float).eps, atol=0):
            _fail('parcel mass/volume mismatch')
        vertices += p.vertex_count; current_ids.append(p.geometry_id)
        arrays['geometry_'+str(i)] = np.frombuffer(p.wkb, dtype=np.uint8)
    if vertices > DEFAULT_GEOMETRY_LIMITS.max_vertices or current_ids != d['current_geometry_ids']:
        _fail('underthrust geometry identity/complexity mismatch')
    if _under_id(d,out._fields,out._work,out._potential,out._displacement) != history_result_id(out):
        _fail('underthrust intrinsic identity mismatch')
    return arrays


def _w04_arrays(out, d):
    _keys(d, _W04_KEYS, 'evolving W04 descriptor')
    if type(out._wet) is not bytes or not 1 <= len(out._wet) <= 2_097_152:
        _fail('invalid W04 cell count')
    n = len(out._wet)
    arrays = dict(values=_view(out._payload,'float64',(n,8)),
        wet=_view(out._wet,'uint8',(n,)), absolute=_view(out._absolute,'float64',(n,4)))
    v, a, wet = arrays['values'], arrays['absolute'], arrays['wet']
    if (d['schema'] != 'atlas.evolving-w04-result.v1' or d['thermal_owner'] != 'flexure' or
            d['vertical_response_owner'] != 'W04' or d['total_reference_result'] is not True or
            d['feedback_applied'] is not False or d['w03_local_displacement'] != 'diagnostic-only-excluded' or
            np.any(wet > 1) or np.any(v[wet == 0,7] != 0)):
        _fail('W04 ownership/known mask mismatch')
    for key in ('plan_id','reference_state','current_state','reference_surface','current_surface',
            'reference_rigidity','current_rigidity','reference_profile','current_profile','reference_operator',
            'current_operator','absolute_reference_load','source_workflow','execution_id'):
        _sha(d[key])
    for key in ('reference_exterior','current_exterior'):
        if d[key] is not None: _sha(d[key])
    for key in ('reference_time_s','time_s'): scalar(d[key],key)
    if d['time_s'] < d['reference_time_s']: _fail('W04 current date precedes reference')
    fixed = d['reference_operator'] == d['current_operator']
    if d['response'] != ('fixed-operator-load-delta' if fixed else 'current-absolute-minus-reference-absolute'):
        _fail('W04 operator/response mismatch')
    with np.errstate(over='ignore', invalid='ignore'):
        if not np.array_equal(a[:,1], a[:,0]+v[:,4]): _fail('W04 absolute load/delta mismatch')
        # The fixed-operator branch intentionally uses compensated load deltas.
        if not fixed and not np.array_equal(v[:,5],a[:,3]-a[:,2]):
            _fail('W04 two-equilibrium displacement mismatch')
    if _w04_id(d,out._payload+out._wet+out._absolute) != history_result_id(out):
        _fail('W04 intrinsic identity mismatch')
    return arrays


def _regional_validate(out, d):
    _keys(d, _REGIONAL_KEYS, 'evolving regional descriptor')
    if type(out.mechanics) is not RegionalMechanicalSnapshot:
        _fail('exact regional snapshot required')
    m = out.mechanics.descriptor(); r = d['request']; definition = m['definition']; mr = m['request']
    _keys(r, {'schema','context','material','body_forces','boundary','surface_pressure','effect_ids',
              'response_owner','total_gravity_owners','interpolation','additional_displacement_ids'}, 'regional request')
    if (d['schema'] != 'atlas.evolving-mechanical-result.v1' or
            d['mechanical_result_id'] != out.mechanics.result_id or
            d['steady_snapshot'] is not True or d['time_advanced'] is not False or
            d['displacement_added'] is not False or d['response_owner'] != 'W07' or
            m['schema'] != 'atlas.regional-mechanical-snapshot.v1' or
            r['schema'] != 'atlas.regional-mechanical-request.v1' or r['response_owner'] != 'W07' or
            r['additional_displacement_ids'] != []):
        _fail('regional response ownership mismatch')
    c = RegionalInputContext(**r['context'])
    centres, vertices = (c.nz,c.nx), (c.nz+1,c.nx+1)
    shapes = dict(force_u_n_m3=(c.nz,c.nx+1),force_w_n_m3=(c.nz+1,c.nx),
        u_m_s=(c.nz,c.nx+1),w_m_s=(c.nz+1,c.nx),dynamic_pressure_pa=centres,
        viscosity_center_pa_s=centres,viscosity_vertex_pa_s=vertices,stress_yy_pa=centres)
    if m['physical_pressure_defined']: shapes['physical_pressure_pa'] = centres
    for axis in ('xx','zz','xz'):
        shape = vertices if axis == 'xz' else centres
        for prefix,suffix in (('strain_','_s_1'),('deviatoric_stress_','_pa'),('stress_','_pa')):
            shapes[prefix+axis+suffix] = shape
    traces = (c.nz+2)*(c.nx+1)+(c.nz+1)*(c.nx+2)
    shapes.update(effective_boundary_reaction_force_n_per_m=(traces,),
                  reaction_coordinates_m=(traces,2),reaction_measures_m=(traces,))
    for side in ('left','right','bottom','top'):
        for component in ('u','w'):
            shape = boundary_coordinates(c.nx,c.nz,c.width_m,c.height_m,side,component)[0].shape
            for prefix,suffix in (('boundary_input_',''),('boundary_velocity_','_m_s'),('boundary_traction_','_pa')):
                shapes[prefix+side+'_'+component+suffix] = shape
    if set(out.array_names) != set(shapes) or any(out.array(k).shape != v for k,v in shapes.items()):
        _fail('regional physical field coverage/support mismatch')
    for key in ('nx','nz','width_m','height_m','frame_id','vertical_datum'):
        if definition[key] != getattr(c,key): _fail('regional support binding mismatch')
    if (d['origin_x_m'] != c.origin_x_m or d['origin_z_m'] != c.origin_z_m or
            mr['time_s'] != c.time_s or mr['epoch_id'] != c.epoch_id or
            mr['force_source'] != _hash(_json(r)) or mr['boundary_source'] != _hash(_json(r)) or
            m['request_id'] != _hash(_json(mr)) or definition['material_source'] != r['material'] or
            mr['plan_id'] != _hash(_json(dict(definition=definition,context=m['context_id'])))):
        _fail('regional input/result binding mismatch')
    blocks = d['input_blocks']
    if (type(blocks) is not list or not 3 <= len(blocks) <= 18 or
            type(r['body_forces']) is not list or len(r['body_forces']) != len(blocks)-2):
        _fail('regional input catalogue mismatch')
    kinds = ['material']+['body-force']*(len(blocks)-2)+['boundary']
    supplied = list(zip(blocks,kinds))
    if d['surface_pressure'] is not None: supplied.append((d['surface_pressure'],'surface-pressure'))
    if (d['surface_pressure'] is None) != (r['surface_pressure'] is None):
        _fail('regional pressure binding mismatch')
    effects, gravity = [], 0
    for block, kind in supplied:
        _keys(block, {'schema','context','kind','source_id','producer_state_id','sampling','effect_ids',
            'boundary_types','units','includes_total_gravity','force_convention','response_owner'}, 'regional input block')
        if (block['schema'] != 'atlas.regional-input-block.v1' or block['kind'] != kind or
                block['context'] != r['context'] or block['response_owner'] != 'W07' or
                block['force_convention'] != 'total-physical-not-pressure-split'):
            _fail('regional producer context mismatch')
        gravity += int(block['includes_total_gravity'])
    # Request construction books boundary effects before body-force effects.
    for block in (blocks[0], blocks[-1], *blocks[1:-1],
                  *((d['surface_pressure'],) if d['surface_pressure'] is not None else ())):
        effects.extend(block['effect_ids'])
    if len(set(effects)) != len(effects) or effects != r['effect_ids'] or gravity > 1 or gravity != r['total_gravity_owners']:
        _fail('regional effect ownership mismatch')
    if definition['boundary_types'] != blocks[-1]['boundary_types']:
        _fail('regional boundary type mismatch')
    # The mechanical snapshot retains both actual viscosity fields.
    material = RegionalMechanicalSnapshot(blocks[0], dict(
        centre=out.array('viscosity_center_pa_s'),vertex=out.array('viscosity_vertex_pa_s')))
    if material.result_id != r['material']: _fail('regional material binding mismatch')
    boundary = {side+'_'+component:out.array('boundary_input_'+side+'_'+component)
                for side in ('left','right','bottom','top') for component in ('u','w')}
    if d['surface_pressure'] is not None:
        if definition['boundary_types']['top']['w'] != 'traction':
            _fail('regional pressure needs top normal traction')
        pressure = RegionalMechanicalSnapshot(d['surface_pressure'],dict(downward=-boundary['top_w']))
        if pressure.result_id != r['surface_pressure']: _fail('regional surface pressure binding mismatch')
        # Original top-normal input was zero, but its signed-zero bytes are
        # not retained after pressure replacement. Do not invent those bytes.
    elif RegionalMechanicalSnapshot(blocks[-1],boundary).result_id != r['boundary']:
        _fail('regional boundary input binding mismatch')
    # Compensated total forces do not retain individual input bytes (including
    # signed zero). The history owner binds the request ID to its real inputs.
    if _hash(_json(d)) != history_result_id(out): _fail('regional wrapper intrinsic identity mismatch')


def _catalogue(arrays, cancel, resource):
    if type(arrays) is not dict or not 1 <= len(arrays) <= MAX_PARCELS+4:
        _fail('invalid array catalogue count')
    specs = {}; total = 0
    for name, value in sorted(arrays.items()):
        _cancel(cancel)
        if (type(name) is not str or len(name) > 128 or type(value) is not np.ndarray or
                value.dtype not in (np.dtype('float64'),np.dtype('uint8')) or
                not value.flags.c_contiguous or len(value.shape) > 4 or
                any(n > 2_097_152 for n in value.shape)):
            _fail('invalid array type/dtype/shape/layout')
        total += value.nbytes
        if total > CAP: _fail('arrays exceed 128 MiB')
        with resource.reserve(value.size+4096,category='tectonic-history-array-check'):
            if not np.isfinite(value).all(): _fail('nonfinite array')
            specs[name] = dict(dtype=value.dtype.str,shape=list(value.shape),nbytes=value.nbytes,
                               sha256=_hash(memoryview(value).cast('B'),cancel))
    return specs, total


def _costs(specs, descriptor, regional):
    raw_size = len(_json(descriptor))+len(_json(regional))
    array_bytes = sum(s['nbytes'] for s in specs.values())
    geometry_bytes = sum(s['nbytes'] for name,s in specs.items() if name.startswith('geometry_'))
    # Includes detached bytes, immutable views, native geometry, JSON trees and
    # nested regional reconstruction; child codecs admit their own extra scratch.
    work = 8*array_bytes+48*geometry_bytes+32*raw_size+8192*len(specs)+65536
    if array_bytes > CAP or work > CAP: _fail('codec work exceeds 128 MiB')
    return dict(array_bytes=array_bytes,metadata_bytes=raw_size,work_bytes=work)


def _pack_history_result(out, *, budget=None, cancel=None):
    """Pack one exact typed result without a plan, timestep or scientific solve."""
    _cancel(cancel); kind = _kind(out); retained = history_result_nbytes(out)
    resource = WorkBudget(CAP,parent=select_budget(budget))
    with resource.reserve(retained+65536,category='tectonic-history-source'):
        d = _record(out); regional = None
        if kind == 'underthrust': arrays = _under_arrays(out,d)
        elif kind == 'evolving-w04': arrays = _w04_arrays(out,d)
        else:
            _regional_validate(out,d)
            arrays,regional = pack_regional_snapshots({'mechanics':out.mechanics},budget=resource,cancel=cancel)
        specs,total = _catalogue(arrays,cancel,resource)
        costs = _costs(specs,d,regional)
        header = dict(schema=SCHEMA,kind=kind,result_id=history_result_id(out),descriptor=d,
                      regional=regional,arrays=specs,resources=costs)
        meta = dict(header,content_id=_hash(_json(header)))
        _json(meta)
        with resource.reserve(costs['work_bytes'],category='tectonic-history-pack'):
            captured = {k:np.frombuffer(v.tobytes(),dtype=v.dtype).reshape(v.shape) for k,v in arrays.items()}
            _cancel(cancel)
            return captured,meta


def _restore_history_result(arrays, metadata, *, budget=None, cancel=None):
    """Restore internal integrity; the owner still checks expected input context."""
    _cancel(cancel); _keys(metadata,_META,'history envelope')
    _json(metadata)
    if metadata['schema'] != SCHEMA or metadata['kind'] not in _KINDS.values():
        _fail('unsupported history schema/type')
    resource = WorkBudget(CAP,parent=select_budget(budget))
    specs,total = _catalogue(arrays,cancel,resource)
    if _json(specs) != _json(metadata['arrays']): _fail('array content/catalogue mismatch')
    d,regional = metadata['descriptor'],metadata['regional']
    costs = _costs(specs,d,regional)
    if (_json(costs) != _json(metadata['resources']) or
            _hash(_json({k:v for k,v in metadata.items() if k != 'content_id'})) != _sha(metadata['content_id'])):
        _fail('content/resource identity mismatch')
    with resource.reserve(costs['work_bytes'],category='tectonic-history-restore'):
        raw = {k:v.tobytes() for k,v in arrays.items()}; kind = metadata['kind']
        if kind == 'underthrust':
            if regional is not None: _fail('unexpected regional payload')
            _keys(d,_UNDER_KEYS,'underthrust descriptor')
            n = len(d['parcels'])
            if not 2 <= n <= MAX_PARCELS or set(arrays) != {'fields','work','potential','displacement'}|{'geometry_'+str(i) for i in range(n)}:
                _fail('underthrust array coverage mismatch')
            polygons = []
            for i in range(n):
                _cancel(cancel)
                if arrays['geometry_'+str(i)].dtype != np.uint8 or arrays['geometry_'+str(i)].ndim != 1:
                    _fail('WKB must be uint8 vector')
                polygons.append(PlanarGeometry.from_wkb(raw['geometry_'+str(i)],frame_id=d['frame_id'],budget=resource))
            out = UnderthrustState(tuple(polygons),tuple(p['parcel_id'] for p in d['parcels']),
                tuple(d['destination_ids']),tuple(d['enthalpy_known']),d['time_s'],d['plan_id'],
                _sha(metadata['result_id']),raw['fields'],raw['work'],raw['potential'],raw['displacement'],_json(d))
            expected = _under_arrays(out,d)
        elif kind == 'evolving-w04':
            if regional is not None or set(arrays) != {'values','wet','absolute'}:
                _fail('W04 array coverage mismatch')
            out = object.__new__(EvolvingW04SupportResult)
            for key,value in dict(_metadata=_json(d),_payload=raw['values'],_wet=raw['wet'],
                    _absolute=raw['absolute'],result_id=_sha(metadata['result_id'])).items():
                object.__setattr__(out,key,value)
            expected = _w04_arrays(out,d)
        else:
            snapshots = restore_regional_snapshots(arrays,regional,budget=resource,cancel=cancel)
            if set(snapshots) != {'mechanics'}: _fail('regional snapshot coverage mismatch')
            out = EvolvingMechanicalResult(snapshots['mechanics'],_sha(metadata['result_id']),_json(d))
            _regional_validate(out,d); expected = arrays
        # Equal raw byte lengths alone must not accept a different shape/dtype.
        if any(a.shape != expected[k].shape or a.dtype != expected[k].dtype for k,a in arrays.items()):
            _fail('restored logical field shape/dtype mismatch')
        history_result_nbytes(out); _cancel(cancel)
        return out


def pack_history_result(out, *, budget=None, cancel=None):
    """Pack one exact supported result with bounded immutable arrays/metadata."""
    try:
        return _pack_history_result(out,budget=budget,cancel=cancel)
    except (TectonicsError,MemoryLimitError):
        raise
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError) as exc:
        raise TectonicsError('tectonic history codec malformed source result') from exc


def restore_history_result(arrays, metadata, *, budget=None, cancel=None):
    """Restore a detached result; the owner validates its expected input context."""
    try:
        return _restore_history_result(arrays,metadata,budget=budget,cancel=cancel)
    except (TectonicsError,MemoryLimitError):
        raise
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError) as exc:
        raise TectonicsError('tectonic history codec malformed stored result') from exc
