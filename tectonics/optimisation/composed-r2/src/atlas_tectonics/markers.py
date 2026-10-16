"""Passive stable-ID material markers for prescribed piecewise-affine motion.

Markers carry no conserved inventory. Cell-cohort volumes remain authoritative;
dropping a marker is never interpreted as subducting its material. This mapping
follows material faces (u=w); arbitrary ALE relative-flow trajectories require a
separate velocity integration and are deliberately not inferred from mesh motion.
"""
from dataclasses import dataclass, field
import hashlib
import json
import numpy as np
from ._validation import snapshot, scalar, TectonicsError
from .materials import _name, _json, _immutable_bytes, _end_time
from .mesh import ColumnGrid1D
from .resources import select_budget
from .regional import _cancelled


@dataclass(frozen=True,slots=True,init=False)
class MaterialMarkers1D:
    marker_ids: tuple[str,...]
    cohort_ids: tuple[str,...]
    time_s: float
    epoch_id: str
    frame_id: str
    marker_state_id: str
    _x: bytes=field(repr=False)
    _strain: bytes=field(repr=False)
    def __init__(self,marker_ids,cohort_ids,positions_m,*,time_s,epoch_id,frame_id,log_stretch=None,budget=None):
        if (type(marker_ids) is not tuple or not marker_ids or len(set(marker_ids))!=len(marker_ids) or
            type(cohort_ids) is not tuple or len(cohort_ids)!=len(marker_ids)):
            raise TectonicsError('unique stable marker IDs with one cohort per marker required')
        for k in marker_ids:_name(k,'marker ID')
        for k in cohort_ids:_name(k,'cohort ID')
        _name(epoch_id,'epoch');_name(frame_id,'frame');time=scalar(time_s,'marker time')
        n=len(marker_ids)
        with select_budget(budget).reserve(64*n+4096,category='material-markers'):
            x=snapshot(positions_m,'marker positions')
            strain=np.zeros(n) if log_stretch is None else snapshot(log_stretch,'marker strain')
            if x.shape!=(n,) or strain.shape!=(n,):raise TectonicsError('one position/strain per marker required')
            xb=_immutable_bytes(x);sb=_immutable_bytes(strain)
            for k,v in (('marker_ids',marker_ids),('cohort_ids',cohort_ids),('time_s',time),
                        ('epoch_id',epoch_id),('frame_id',frame_id),('_x',xb),('_strain',sb)):
                object.__setattr__(self,k,v)
            h=hashlib.sha256(_json({'schema':'atlas.material-markers.v1','ids':marker_ids,'cohorts':cohort_ids,
                                 'time_s':time,'epoch':epoch_id,'frame':frame_id}))
            h.update(xb);h.update(sb);object.__setattr__(self,'marker_state_id',h.hexdigest())
    @property
    def positions_m(self):return np.frombuffer(self._x,np.float64)
    @property
    def log_stretch(self):return np.frombuffer(self._strain,np.float64)
    def __deepcopy__(self,memo):memo[id(self)]=self;return self


def move_material_markers(markers,source,target,duration_s,*,budget=None,cancel=None):
    """Exact local affine position map; log stretches add along that material path."""
    _cancelled(cancel)
    if type(markers) is not MaterialMarkers1D or type(source) is not ColumnGrid1D or type(target) is not ColumnGrid1D:
        raise TectonicsError('typed markers and source/target meshes required')
    if source.cells!=target.cells or source.frame_id!=target.frame_id or source.frame_id!=markers.frame_id:
        raise TectonicsError('material map needs corresponding faces in the same frame')
    dt=scalar(duration_s,'duration',nonnegative=True);end=_end_time(markers,dt)
    if dt==0 and source!=target:raise TectonicsError('nonzero material motion needs nonzero time')
    with select_budget(budget).reserve(64*len(markers.marker_ids)+4096,category='marker-motion'):
        from ._mesh_native import mapped_points
        try:
            x,stretch=mapped_points(markers.positions_m,source.edges_m,target.edges_m)
            strain=markers.log_stretch+np.log(stretch)
            result=MaterialMarkers1D(markers.marker_ids,markers.cohort_ids,x,time_s=end,
                epoch_id=markers.epoch_id,frame_id=markers.frame_id,log_stretch=strain,budget=budget)
            _cancelled(cancel);return result
        except (ValueError,OverflowError,FloatingPointError) as exc:raise TectonicsError(str(exc)) from exc


def save_material_markers(markers,store,*,budget=None,cancel=None):
    """Persist passive histories through ArrayStore; no separate marker-file format."""
    if type(markers) is not MaterialMarkers1D:raise TectonicsError('typed markers required')
    meta={'schema':'atlas.material-markers.v1','marker_ids':list(markers.marker_ids),
          'cohort_ids':list(markers.cohort_ids),'time_s':markers.time_s,
          'epoch_id':markers.epoch_id,'frame_id':markers.frame_id}
    return store.put(markers.marker_state_id,{'positions_m':markers.positions_m,'log_stretch':markers.log_stretch},
                     meta,budget=budget,cancel=cancel)


def load_material_markers(store,identity,*,budget=None):
    from .materials import _sha
    _sha(identity,'marker snapshot')
    data=store.get(identity,budget=budget)
    if data is None:return None
    meta=store.metadata(identity)
    if (set(data)!={'positions_m','log_stretch'} or type(meta) is not dict or
            set(meta)!={'schema','marker_ids','cohort_ids','time_s','epoch_id','frame_id'} or
            meta['schema']!='atlas.material-markers.v1'):
        raise TectonicsError('invalid marker snapshot')
    result=MaterialMarkers1D(tuple(meta['marker_ids']),tuple(meta['cohort_ids']),data['positions_m'],
        log_stretch=data['log_stretch'],time_s=meta['time_s'],epoch_id=meta['epoch_id'],frame_id=meta['frame_id'],budget=budget)
    if result.marker_state_id!=identity:raise TectonicsError('marker identity mismatch')
    return result
