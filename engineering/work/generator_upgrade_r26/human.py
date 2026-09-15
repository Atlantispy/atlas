"""Exact in-memory settlement construction and static transport-field adapters.

The reviewed native producers remain authoritative about their limitations.
Geometry is WKB; arrays retain bytes/dtype; missing coordinates are not zero.
"""
from copy import deepcopy
import math
import struct
from types import SimpleNamespace
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely import wkb
from affine import Affine
from . import environment
from .provenance import sha

OPERATIONS = {'settlement_candidates':('settlements',),
              'transport_fields':('infrastructure_connectivity',)}
TAG = '__r26_native_type__'


def pack(value):
    if isinstance(value,np.ndarray):
        return {TAG:'array','value':environment.pack_array(value)}
    if isinstance(value,pd.DataFrame):
        return {TAG:'table','columns':list(value.columns),'dtypes':[str(t) for t in value.dtypes],
            'index':pack(list(value.index)),'index_names':pack(list(value.index.names)),
            'data':[[pack(x) for x in row] for row in value.itertuples(index=False,name=None)],
            'attrs':pack(value.attrs)}
    if isinstance(value,BaseGeometry):
        return {TAG:'geometry','wkb_hex':value.wkb_hex}
    if value is pd.NA:
        return {TAG:'NA'}
    if isinstance(value,np.generic):
        return pack(value.item())
    if type(value) is float and not math.isfinite(value):
        return {TAG:'float64','hex':struct.pack('>d',value).hex()}
    if isinstance(value,Affine):
        return {TAG:'affine','items':list(value)}
    if type(value) is tuple:
        return {TAG:'tuple','items':[pack(x) for x in value]}
    if type(value) is list:
        return [pack(x) for x in value]
    if type(value) is dict:
        if TAG in value or any(type(k) is not str for k in value):
            raise ValueError('explicit non-reserved string mapping keys required')
        return {key:pack(x) for key,x in value.items()}
    if type(value) in (str,int,float,bool,type(None)):
        return value
    raise ValueError('unsupported exact native value: '+str(type(value)))


def unpack(value):
    if type(value) is list:
        return [unpack(x) for x in value]
    if type(value) is not dict:
        return value
    if TAG not in value:
        return {key:unpack(x) for key,x in value.items()}
    kind = value[TAG]
    fields = {'array':{TAG,'value'},'geometry':{TAG,'wkb_hex'},'NA':{TAG},
        'float64':{TAG,'hex'},'tuple':{TAG,'items'},'affine':{TAG,'items'},
        'table':{TAG,'columns','dtypes','index','index_names','data','attrs'}}
    if kind not in fields or set(value) != fields[kind]:
        raise ValueError('exact native transport record required')
    if kind == 'array': return environment.unpack_array(value['value'])
    if kind == 'geometry': return wkb.loads(value['wkb_hex'],hex=True)
    if kind == 'NA': return pd.NA
    if kind == 'float64': return struct.unpack('>d',bytes.fromhex(value['hex']))[0]
    if kind == 'tuple': return tuple(unpack(x) for x in value['items'])
    if kind == 'affine': return Affine(*value['items'])
    columns = value['columns']
    if len(columns)!=len(value['dtypes']) or len(set(columns))!=len(columns):
        raise ValueError('exact unique table columns required')
    table = pd.DataFrame([[unpack(x) for x in row] for row in value['data']],columns=columns)
    for name,dtype in zip(columns,value['dtypes']):
        table[name] = table[name].astype(dtype)
    table.index = unpack(value['index'])
    table.index.names = unpack(value['index_names'])
    table.attrs = unpack(value['attrs'])
    return table


def native_inputs(operation,inputs):
    args = unpack(deepcopy(inputs))
    if operation == 'settlement_candidates':
        args['candidates_tmp'] = [SimpleNamespace(**dict(item,row=pd.Series(item['row'])))
                                  for item in args['candidates_tmp']]
    return args


def invoke(module,operation,inputs):
    args = native_inputs(operation,inputs)
    if operation == 'settlement_candidates':
        result = module.build_settlement_candidates(**args)
    elif operation == 'transport_fields':
        # Static controls are an explicit optional producer step, not inferred.
        if 'control_inputs' in args:
            if 'ctl' in args: raise ValueError('supply controls or their inputs, not both')
            args['ctl'] = module.transport_controls(**args.pop('control_inputs'))
        result = module.build_transport_fields(**args)
    else:
        raise ValueError('unknown human operation')
    return {'schema':'diadem.r26-exact-human-product','operation':operation,
        'native_result':pack(result),'source_status':'WORKING NON-CANON',
        'physical_acceptance_granted':False}


class Adapter:
    def __init__(self,operation,cache=True,cache_root=None,shared=None):
        if operation not in OPERATIONS: raise ValueError('unknown human operation')
        self.operation = operation
        pool = {} if shared is None else shared
        if 'reviewed_human_resource' not in pool:
            pool['reviewed_human_resource'] = environment._reviewed_human_resource()
        self.module,sources,self._check = pool['reviewed_human_resource']
        self.source_signature = sha({'operation':operation,'native_sources':sources,
            'runtime':self.module._R26_RUNTIME})
        self.verify()

    def verify(self):
        self._check()

    def run(self,inputs,incoming):
        if set(inputs)&set(incoming): raise ValueError('dependency input collision')
        self.verify()
        result = invoke(self.module,self.operation,{**inputs,**incoming})
        self.verify()
        return result


def baseline(operation,inputs,**options):
    module,_,verify = environment._reviewed_human_resource()
    verify()
    result = invoke(module,operation,inputs)
    verify()
    return result


def fixtures():
    from shapely.geometry import box
    row = dict(form_id='A',haus='Test',spatial_domain='surface',representation_status='DIRECT_2D',
        candidate_geometry_class='POINT_OR_POLYGON',pair_id='PAIR',species='Test species',
        settlement_form='A',scope='DIRECT',capital_or_core_role='NONE',canon_status='UNKNOWN',
        permanence_class='UNKNOWN',principal_function='UNKNOWN',must_have_evidence='SYNTHETIC TEST',
        disqualifiers='UNKNOWN',requires_surface_proxy=False)
    candidate = dict(row=row,cells=np.array([[0,0,0]],dtype=np.int64),raw_max=1.,smooth_max=1.,
        fallback=False,extraction_class='SYNTHETIC',sigma=4.,radius=20)
    settlement = dict(candidates_tmp=[candidate],cell_offsets=np.zeros(1025,dtype=np.int64),
        fragment_row=np.zeros(0,dtype=np.int64),fragment_col=np.zeros(0,dtype=np.int64),
        fragment_area=np.zeros(0),fragment_flags=np.zeros(0,dtype=np.int64),
        fragment_graph_component=np.zeros(0,dtype=np.int64),
        baronies=pd.DataFrame(dict(barony_id=[1],county_uid=['C'],duchy_uid=['D'],
            surface_fill_name=['Test'],geometry=[box(0,0,32,32)])))
    module,_,_ = environment._reviewed_human_resource()
    shape = (9,9)
    zero = np.zeros(shape,dtype=np.float32)
    gl = {n:zero.copy() for n in ['mean_terrain_slope_degrees','maximum_100m_cell_slope_degrees',
        'subcell_relief_m','ruggedness_11km_m','ruggedness_31km_m','tpi_11km_m','tpi_31km_m',
        'accepted_stream_order_context']}
    gl['active_domain'] = np.ones(shape,dtype=np.uint8)
    cryo = {n:zero.copy() for n in ['snow_climate_regime_1_none_2_seasonal_3_sensitive_4_robust',
        'possible_small_ice_climate_support_not_outline','robust_small_ice_climate_support_not_outline']}
    namespace,_ = module.composition()._transport_namespace(shape)
    transport = dict(z=zero,full_gl=gl,full_cryo=cryo,
        full_mh={n:zero.copy() for n in namespace['PROCESS_BANDS']},
        control_inputs={n:zero.copy() for n in ['p4','divide','major','minor','sea_fraction']},
        divide_geojson={'features':[{'geometry':{'type':'LineString',
            'coordinates':[[0,0],[8,0],[8,8],[0,8],[0,0]]}}]})
    return {'settlement_candidates':pack(settlement),'transport_fields':pack(transport)}
