"""Lossless typed output ports; no physics, spatial remapping or restart factory.

SPDX-License-Identifier: AGPL-3.0-only

Arrays retain their native immutable backing. Mixed-unit arrays carry ordered
column specifications; unknown values retain their producer's validity masks.
The caller owns retained output memory and authenticates the producing workflow.
An export is descriptive data, not proof of scientific acceptance or a checkpoint.
"""
from dataclasses import fields as dataclass_fields, is_dataclass
import json

import numpy as np

from ._validation import TectonicsError
from .regional_workflow import RegionalWorkflowState
from .w03_workflow import W03ColumnState
from .w04_workflow import W04SupportResult
from .extension_workflow import ExtensionWorkflowCheckpoint
from .w06_workflow import W06WorkflowCheckpoint
from .w07_workflow import W07WorkflowOutput
from .w08_workflow import W08Output
from .spreading_cooling import SpreadingThermalState
from .spreading_history_cooling import HistoryThermalState
from .margin_cooling import MarginSupportResult
from .regional_execution import RegionalMechanicalSnapshot
from .tectonic_history import TectonicHistoryOutput
from .underthrust import UnderthrustState
from .evolving_flexure import EvolvingW04SupportResult
from .evolving_mechanics import EvolvingMechanicalResult


_UNITS = (('_j_kg_k', 'J/(kg K)'), ('_j_m3_k', 'J/(m3 K)'), ('_w_m_k', 'W/(m K)'),
          ('_kg_m3', 'kg/m3'), ('_j_kg', 'J/kg'), ('_w_m2', 'W/m2'), ('_w_m3', 'W/m3'),
          ('_m2_s', 'm2/s'), ('_m3_s', 'm3/s'), ('_m_s2', 'm/s2'),
          ('_n_per_m', 'N/m'), ('_j_m2', 'J/m2'), ('_n_m3', 'N/m3'),
          ('_kg_m2', 'kg/m2'), ('_pa_s', 'Pa s'), ('_m_s', 'm/s'),
          ('_s_1', '1/s'), ('_m3', 'm3'), ('_m2', 'm2'), ('_pa', 'Pa'),
          ('_kg', 'kg'), ('_j', 'J'), ('_k', 'K'), ('_m', 'm'), ('_s', 's'))
_DIMENSIONLESS = frozenset(('void_ratio', 'ocean_fraction', 'deformation_gradient',
    'cell_offsets', 'row_cell', 'phase_row', 'unit_code', 'province_code',
    'phase_cohort_code', 'phase_material_code', 'phase_kind', 'owner_pairs',
    'selected_rows', 'centre_strip_index'))


def _json(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')))
    except (TypeError, ValueError, OverflowError) as exc:
        raise TectonicsError('workflow export needs finite JSON metadata') from exc


def _public(value):
    """Native dataclass metadata, excluding byte payloads explicitly exported below."""
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if type(value) in (tuple, list):
        return [_public(item) for item in value]
    if type(value) is dict:
        return {key: _public(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        out = {}
        for field in dataclass_fields(value):
            if field.name.startswith('_'):
                continue
            item = getattr(value, field.name)
            if isinstance(item, np.ndarray):
                out[field.name] = {'array_field': field.name}
            elif field.name == 'source_state':
                # Live authored input is a dependency, not a serialisable output.
                out[field.name] = {'state_id': item.state_id,
                                   'external_restart_dependency': True}
            else:
                out[field.name] = _public(item)
        return out
    raise TectonicsError('unsupported native metadata component: '+type(value).__name__)


class _Port:
    def __init__(self):
        self.fields = {}
        self.specs = {}

    def add(self, name, value, *, support, owner, units=None, known=None, columns=None):
        if type(value) is not np.ndarray or value.dtype.kind not in 'biuf':
            raise TectonicsError('workflow export requires plain numeric arrays: '+name)
        backing = value
        while type(backing) is np.ndarray:
            backing = backing.base
        if value.flags.writeable or type(backing) is not bytes:
            raise TectonicsError('workflow export requires immutable byte backing: '+name)
        if not np.isfinite(value).all():
            raise TectonicsError('nonfinite workflow export field: '+name)
        if name in self.fields:
            raise TectonicsError('duplicate workflow export field: '+name)
        leaf = name.rsplit('.', 1)[-1]
        if units is None:
            if leaf in _DIMENSIONLESS or value.dtype.kind in 'biu' or leaf.endswith('_known'):
                units = '1'
            else:
                units = next((unit for suffix, unit in _UNITS if leaf.endswith(suffix)), None)
        if units is None:
            raise TectonicsError('no declared export units for field: '+name)
        self.fields[name] = value
        self.specs[name] = dict(units=units, support=support, owner=owner,
            known=known or {'kind': 'all', 'meaning': 'finite native output; no empirical-accuracy claim'},
            dtype=value.dtype.str, shape=list(value.shape))
        if columns is not None:
            self.specs[name]['columns'] = columns

    def material(self, state, prefix='material'):
        self.add(prefix+'.thickness_m', state.thickness_m,
                 support='cohort x ordered regional cell', owner='W02 conserved material inventory')
        return dict(state_id=state.state_id, native=state.descriptor())

    def w04(self, result, prefix='support'):
        columns = [dict(name=name, units=unit) for name, unit in (
            ('inventory_load', 'Pa'), ('void_replacement_load', 'Pa'),
            ('thermal_load', 'Pa'), ('external_load', 'Pa'), ('total_downward_load', 'Pa'),
            ('downward_displacement_from_reference', 'm'), ('sediment_surface_change_up', 'm'),
            ('reservoir_surface_change_up', 'm'))]
        columns[-1]['known'] = {'mask_field': prefix+'.reservoir_surface_known',
                               'meaning': 'water exists at both reference and current dates'}
        self.add(prefix+'.values', result.values, units=[row['units'] for row in columns],
                 support='ordered W03 cells x named columns', owner='W04 single elastic response',
                 known={'kind': 'per-column', 'meaning': 'last column requires the retained water mask'},
                 columns=columns)
        self.add(prefix+'.reservoir_surface_known', result.reservoir_surface_known,
                 support='ordered W03 cells', owner='W04 water-surface validity')
        return dict(result_id=result.result_id, native=result.descriptor())

    def snapshot(self, snapshot, prefix):
        if type(snapshot) is not RegionalMechanicalSnapshot:
            raise TectonicsError('exact RegionalMechanicalSnapshot required')
        native = snapshot.descriptor()
        for name in snapshot.array_names:
            units = None
            if name.startswith('boundary_input_'):
                side, component = name[len('boundary_input_'):].rsplit('_', 1)
                kind = native['definition']['boundary_types'][side][component]
                units = 'm/s' if kind == 'velocity' else 'Pa' if kind == 'traction' else None
            support = _snapshot_support(name, native)
            known = None
            if name in ('stress_xx_pa','stress_zz_pa','stress_yy_pa') and native.get('physical_pressure_defined') is False:
                known = {'kind': 'declared-gauge', 'meaning': native['stress_pressure_convention'],
                         'physical_absolute_pressure_known': False}
            self.add(prefix+'.'+name, snapshot.array(name), units=units, support=support,
                     owner='native snapshot '+native['schema'], known=known)
        return dict(result_id=snapshot.result_id, native=native)


def _snapshot_support(name, metadata):
    declared = metadata.get('field_support')
    if isinstance(declared, str):
        return declared+'; native field '+name
    if name == 'cohort_partial_thickness_m':
        return 'source cohort x source regional column'
    if name in ('phase_volume_m3','reference_mass_kg'):
        return 'source cohort x mechanical vertical cell x mechanical horizontal cell'
    if name == 'source_face_velocity_m_s':
        return 'source regional N+1 column faces'
    if name == 'surface_height_m':
        return 'Q2 horizontal surface graph nodes'
    if name.startswith('boundary_'):
        return 'native boundary trace ordering; '+name
    if name.startswith(('u_', 'force_u_')):
        return 'MAC vertical faces'
    if name.startswith(('w_', 'force_w_')):
        return 'MAC horizontal faces'
    if '_xz_' in name or '_vertex_' in name:
        return 'MAC shear vertices'
    if name == 'density_w_kg_m3':
        return 'MAC horizontal faces'
    if name.startswith(('reaction_', 'effective_boundary_reaction_')):
        return 'full native boundary trace ordering in descriptor.field_support'
    if name == 'temperature_k' or '_center_' in name or name in ('physical_pressure_pa','dynamic_pressure_pa') or name.startswith(('strain_','stress_','deviatoric_stress_')):
        return 'mechanical vertical cell x horizontal cell centres'
    return 'native snapshot support and shape; '+name+'; see complete descriptor'


def _regional(out, port):
    samples = out.initial_samples
    md = samples.descriptor()
    if md['requested_fields']:
        raise TectonicsError('W12 regional port does not infer units for optional authored fields')
    masks = {'temperature_k': 'temperature_known', 'temperature_quadrature_error_k': 'temperature_known',
             'solid_volume_m3': 'solid_volume_known', 'reference_mass_kg': 'reference_mass_known',
             'field_values': 'field_known'}
    for name in md['arrays']:
        units = [] if name == 'field_values' else 'WKB bytes' if name.startswith('support_') else None
        known = None if name not in masks else dict(kind='mask', mask_field='initial_samples.'+masks[name],
                                                   meaning='false entries are native placeholders, not known values')
        port.add('initial_samples.'+name, samples.array(name), support='native sampling cells/rows; descriptor arrays and cells',
                 owner='W01 initial geological sampling, not evolved thermal state', units=units, known=known)
    forcing_md = out.forcing.descriptor()
    for name, value in out.forcing.arrays().items():
        port.add('forcing.'+name, value, support='N+1 regional faces and original sided sample rows',
                 owner='W01 supplied frozen motion')
    return dict(native=out.descriptor(), material=port.material(out.material),
                initial_samples=md, forcing=forcing_md, forcing_samples=out.forcing.samples.descriptor())


def _columns(out, port):
    for name in ('grain_volume_m3', 'void_ratio', 'maximum_effective_stress_pa', 'area_m2', 'top_effective_stress_pa'):
        port.add('compaction.'+name, getattr(out.compaction, name),
                 support='ordered solid parcels x columns, or column area/traction', owner='W03 drained compaction')
    return dict(native=out.descriptor(), material=port.material(out.material),
                compaction=dict(state_id=out.compaction.state_id, native=out.compaction.descriptor()),
                source_workflow_id=out.source_workflow.workflow_id,
                thermal_diagnostics='not evaluated by export; thermal binding retained in native descriptor')


def _extension(out, port):
    state = out.state
    port.add('state.exchange_m2', state.exchange_m2, support='cohort x left/right boundary',
             owner='W05 signed area exchange into region')
    columns = [dict(name=name, units=unit) for name, unit in (
        ('downward_load','Pa'), ('downward_displacement','m'), ('unflexed_surface_change','m'),
        ('surface_elevation','m'), ('base_elevation','m'), ('fault_elevation','m'),
        ('crust_thickness','m'), ('hangingwall_thickness','m'), ('footwall_thickness','m'),
        ('mantle_volume_into_column','m3'))]
    port.add('support.cell_means', out.support.cell_means, units=[x['units'] for x in columns],
             support='regional cell means x named columns', owner='W05 single elastic response', columns=columns)
    port.add('support.face_centre_response', out.support.face_centre_response,
             units=['m','1','1/m','1/m2'], support='face,centre,face ordering; w,w-prime,w-second,w-third',
             owner='W05 point diagnostics of same elastic response')
    return dict(checkpoint_id=out.checkpoint_id, output_index=out.output_index,
        state=dict(state_id=state.state_id, plan_id=state.plan_id, intervals=state.intervals,
                   max_courant=state.max_courant, material=port.material(state.material, 'state.material')),
        support=dict(result_id=out.support.result_id, native=out.support.descriptor()))


def _ocean(state, port):
    phases = state.cell_values.shape[1]-5
    units = ['K']*phases+['kg/m2','m','m','J/m2','J/m2']
    columns = ['phase_temperature_'+str(i) for i in range(phases)]+[
        'thermal_sheet_anomaly','downward_subsidence','water_depth','outward_top_heat','outward_base_heat']
    for name in ('cell_values','centre_values'):
        mask = 'state.ocean_fraction' if name == 'cell_values' else 'state.centre_valid'
        port.add('state.'+name, getattr(state,name), units=units, columns=columns,
            support='occupied-ocean cell means' if name == 'cell_values' else 'cell-centre points',
            owner='W06 cooling and single thermal support',
            known=dict(kind='positive-mask' if name == 'cell_values' else 'mask', mask_field=mask,
                       meaning='unoccupied entries are placeholders, never zero-K ocean'))
    for name in ('ocean_fraction','centre_valid','water_accounts_m3'):
        port.add('state.'+name, getattr(state,name), support='native ocean cells or named water account vector',
                 owner='W06 finite ocean material/water')
    port.add('state.heat_accounts_j', state.heat_accounts_j,
             units=['J']*(state.heat_accounts_j.size-1)+['1'],
             support='birth,remaining,basal,remaining,surface,resident,L/R export,residual,relative',
             owner='W06 complete finite heat account')
    motion = state.motion
    port.add('state.motion.accounts_kg', motion.accounts_kg, support='phase x created,remaining,resident,left export,right export,residual',
             owner='W06 finite material')
    if type(state) is HistoryThermalState:
        port.add('state.motion.intersections', motion.intersections, units=['1','1','m','s','s'],
                 support='cell index,strip index,width,youngest age,oldest age', owner='W06 exact birth-strip intersections')
        for name in ('centre_age_s','centre_strip_index','centre_valid'):
            port.add('state.motion.'+name, getattr(motion,name), support='regional cell centres',
                owner='W06 changing motion history', known=None if name == 'centre_valid' else
                dict(kind='mask',mask_field='state.motion.centre_valid',meaning='empty-centre values are placeholders'))
    else:
        port.add('state.motion.cell_geometry', motion.cell_geometry, units=['m','s','s'],
                 support='side x cell x occupied width,youngest age,oldest age', owner='W06 birth geometry',
                 known=dict(kind='first-column-positive', meaning='ages known only for positive occupied width'))
    return _public(state)


def _w06(out, port):
    state = out.state
    if type(state) in (SpreadingThermalState, HistoryThermalState):
        kind = 'constant' if type(state) is SpreadingThermalState else 'history'
        md = _ocean(state, port)
    elif type(state) is MarginSupportResult:
        kind = 'margin'
        for name in ('depth_edges_m','mean_temperature_k','initial_reference_temperature_k','temperature_change_k','outward_heat_j_m2'):
            port.add('state.thermal.'+name, getattr(state.thermal,name),
                     support='source depth edges/layer means; heat vector is outward top/base', owner='W06 inherited margin')
        md = _public(state)
    else:
        raise TectonicsError('unsupported W06 checkpoint state type')
    return kind, dict(checkpoint_id=out.checkpoint_id, output_index=out.output_index, state=md)


def _w08(out, port):
    inventory = out.inventory
    for name in ('component_mass_kg','enthalpy_j','formation_time_s','mass_kg'):
        port.add('inventory.'+name, getattr(inventory,name), support='inventory nodes x components, or one value per node',
                 owner='W08 single finite inventory; regional views do not duplicate stocks')
    regional = out.regional
    for name in ('mass_kg','enthalpy_j','volume_m3','thickness_m','component_mass_kg',
                 'load_change_pa','surface_addition_m','basal_addition_m'):
        port.add('regional.'+name, getattr(regional,name), support='native node/parcel/component support in regional descriptor',
                 owner='W08 diagnostic regional view of same inventory')
    port.add('deformation_gradient', out.deformation_gradient, support='native affine regional 2x2 gradient',
             owner='W08 prescribed motion')
    geometry = {}
    for label in ('polygons','reference_polygons'):
        records = []
        for i, polygon in enumerate(getattr(out,label)):
            name = label+'.'+str(i)
            port.add(name, np.frombuffer(polygon.wkb,dtype=np.uint8), units='WKB bytes',
                     support='native planar polygon; no rasterisation or invented mapping', owner='W08 supplied parcel geometry')
            records.append(dict(field=name, geometry_id=polygon.geometry_id, native=polygon.descriptor()))
        geometry[label] = records
    return dict(native=out.descriptor(), checkpoint_id=out.checkpoint_id, interval_index=out.interval_index,
                inventory=dict(inventory_id=inventory.inventory_id,native=inventory.descriptor()),
                regional=dict(view_id=regional.view_id,native=regional.descriptor()), geometry=geometry)


def _history_result(result, port):
    if type(result) is EvolvingW04SupportResult:
        md = port.w04(result,'result')
        port.add('result.absolute_values',result.absolute_values,units=['Pa','Pa','m','m'],
                 support='ordered cells x reference/current absolute pressure,reference/current downward displacement',
                 owner='W04 two absolute equilibria; total reference difference, not accumulated increments')
        return 'evolving-w04',result.result_id,md
    if type(result) is EvolvingMechanicalResult:
        md = dict(result_id=result.result_id,native=result.descriptor(),
                  mechanics=port.snapshot(result.mechanics,'result.mechanics'))
        return 'evolving-regional',result.result_id,md
    if type(result) is not UnderthrustState:
        raise TectonicsError('unsupported exact tectonic history result type')
    for name in ('volume_m3','mass_kg','enthalpy_j','boundary_work_j','gravitational_change_j','displacement_m'):
        support = 'parcel x named receiving/exterior destination'
        if name == 'boundary_work_j': support = 'supplied hangingwall/host generalised work'
        if name == 'gravitational_change_j': support = 'one gravitational change per parcel'
        if name == 'displacement_m': support = 'supplied hangingwall/host horizontal slip'
        known = None if name != 'enthalpy_j' else dict(kind='row-mask',mask_field='result.enthalpy_known',
            meaning='unknown parcel enthalpy rows are placeholders, never zero heat')
        port.add('result.'+name,getattr(result,name),support=support,owner='underthrust finite parcels and once-owned work',known=known)
    known = np.frombuffer(bytes(result.enthalpy_known),dtype=np.bool_)
    port.add('result.enthalpy_known',known,support='one known flag per parcel',owner='source enthalpy knowledge')
    geometry = []
    for i,polygon in enumerate(result.polygons):
        name = 'result.polygons.'+str(i)
        port.add(name,np.frombuffer(polygon.wkb,dtype=np.uint8),units='WKB bytes',
                 support='native x/z parcel geometry; no rasterisation',owner='underthrust material geometry')
        geometry.append(dict(field=name,geometry_id=polygon.geometry_id,native=polygon.descriptor()))
    return 'underthrust',result.state_id,dict(state_id=result.state_id,native=result.descriptor(),geometry=geometry)


def describe_workflow_output(output):
    """Describe an exact supported typed output without evaluating any physics.

    Native checkpoint IDs are references only. Resume still requires the original
    typed inputs, schedule, compatible preparation/runtime and native history store.
    This function validates the export representation, not producer authenticity.
    """
    port = _Port()
    cls = type(output)
    if cls is RegionalWorkflowState:
        route, identity, descriptor = 'w01-w02-regional.v1', output.workflow_id, _regional(output,port)
    elif cls is W03ColumnState:
        route, identity, descriptor = 'w03-columns.v1', output.state_id, _columns(output,port)
    elif cls is W04SupportResult:
        route, identity, descriptor = 'w04-support.v1', output.result_id, port.w04(output)
    elif cls is ExtensionWorkflowCheckpoint:
        route, identity, descriptor = 'w05-extension.v1', output.checkpoint_id, _extension(output,port)
    elif cls is W06WorkflowCheckpoint:
        kind, descriptor = _w06(output,port)
        route, identity = 'w06-'+kind+'.v1', output.checkpoint_id
    elif cls is W07WorkflowOutput:
        receipt = output.descriptor()
        if receipt['route'] not in ('steady','thermal','surface'):
            raise TectonicsError('unsupported W07 output route')
        route, identity = 'w07-'+receipt['route']+'.v1', output.output_id
        descriptor = dict(native=receipt, checkpoint_id=output.checkpoint_id, output_index=output.output_index,
            state=port.snapshot(output.state,'state'), mechanics=port.snapshot(output.mechanics,'mechanics'))
    elif cls is W08Output:
        route, identity, descriptor = 'w08-joined.v1', output.output_id, _w08(output,port)
    elif cls is TectonicHistoryOutput:
        kind, result_id, result = _history_result(output.result,port)
        route,identity = 'tectonic-history-'+kind+'.v1',output.output_id
        descriptor = dict(native=output.descriptor(),checkpoint_id=output.checkpoint_id,index=output.index,
                          time_s=output.time_s,result_id=result_id,result=result)
    elif cls in (UnderthrustState,EvolvingW04SupportResult,EvolvingMechanicalResult):
        kind,identity,descriptor = _history_result(output,port)
        route = 'tectonic-'+kind+'.v1'
    else:
        raise TectonicsError('unsupported exact workflow output type: '+cls.__name__)
    if type(identity) is not str or not identity:
        raise TectonicsError('native workflow output identity required')
    descriptor = _json(descriptor)
    native_ids = {}
    def collect(value, path=''):
        if type(value) is dict:
            for key, item in value.items():
                child = path+'.'+key if path else key
                if (key.endswith('_id') or key.endswith('_ids')) and item is not None:
                    native_ids[child] = item
                collect(item,child)
        elif type(value) is list:
            for index,item in enumerate(value):
                collect(item,path+'.'+str(index))
    collect(descriptor)
    return dict(route=route, source_output_id=identity, descriptor=descriptor,
        fields=port.fields, field_specs=_json(port.specs), dependencies=dict(native_ids=native_ids,
            export_is_restart=False, restart_requirements=[
                'original typed source inputs and complete requested-output schedule',
                'compatible native producer preparation, numerical policy and source/runtime identities',
                'native history store and its required accepted parent/checkpoint records'],
            export_scope='complete published fields and native output metadata; no live factors or reconstructed physics'))
