"""Minor-great-circle polygons/traces on an explicit spherical reference frame.

Gnomonic coordinates are used ONLY for topology: on a sphere minor great-circle
arcs map to straight segments. Distances/areas are evaluated on the sphere.
Each geometry must fit an explicitly conditioned open-hemisphere chart. Features
crossing a longitude seam or covering a pole are supported; antipodal edges, a
whole-sphere ring or a polygon crossing its chart horizon are not guessed/repaired.
Large worlds may use multiple explicit patches, but their seam ownership is W01
stage 3, not a claim made by this primitive layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString
from shapely.errors import GEOSException

from ._validation import read_array, scalar
from .coordinates import SphericalFrame
from .resources import elements, select_budget
from .geometry import (GeometryError, GeometryLimits, PlanarGeometry, _limits, _json,
    _point_shape, _vertices, _preflight_vertices, _validate_shape, _typed_frozen,
    _overlay_budget, _check_cancel)

_SCHEMA_SPHERE='atlas.spherical-feature.v1'
_DEFAULT_ANGULAR_BAND=64*np.finfo(float).eps


def _directions(value):
    a=read_array(value,'spherical directions')
    scale=np.max(np.abs(a),axis=-1,keepdims=True)
    if np.any(scale==0):raise GeometryError('zero direction has no spherical position')
    a=a/scale
    return a/np.sqrt(np.sum(a*a,axis=-1,keepdims=True))


@dataclass(frozen=True,slots=True)
class SphericalChart:
    """Identified gnomonic chart. min_cosine bounds numerical distortion, not physics.

    Directions (not longitudes) select a centre; radius and axes come from stage 1.
    The right-handed tangent basis is deterministic and is not a regional ENU map.
    Projected coordinates are dimensionless. They are never reported as metres.
    """
    sphere: SphericalFrame
    centre: tuple[float,float,float]
    min_cosine: float=1e-3
    _basis: bytes=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        if type(self.sphere) is not SphericalFrame:raise GeometryError('SphericalFrame required')
        if _point_shape(self.centre,3)!=(3,):raise GeometryError('chart centre must have three components')
        c=_directions(self.centre)
        margin=scalar(self.min_cosine,'min_cosine',positive=True)
        if margin>=1:raise GeometryError('chart min_cosine must be below one')
        axis=np.eye(3)[int(np.argmin(np.abs(c)))]
        e=np.cross(axis,c);e/=np.linalg.norm(e);n=np.cross(c,e)
        object.__setattr__(self,'centre',tuple(float(x) for x in c))
        object.__setattr__(self,'min_cosine',margin)
        object.__setattr__(self,'_basis',np.array([e,n,c]).tobytes())

    @classmethod
    def from_descriptor(cls, desc):
        """Restore the exact captured centre; do not normalise and drift on each load."""
        if type(desc) is not dict or set(desc)!= {'schema','sphere','centre','min_cosine'} or desc['schema']!='atlas.gnomonic-chart.v1':
            raise GeometryError('invalid spherical chart descriptor')
        try:
            sd=desc['sphere'];sphere=SphericalFrame(sd['radius_m'],sd['frame_id'])
            if sphere.descriptor()!=sd:raise GeometryError('sphere descriptor mismatch')
            if _point_shape(desc['centre'],3)!=(3,):raise GeometryError('invalid stored centre')
            c=read_array(desc['centre'],'stored centre')
            if abs(math.hypot(*c)-1)>16*np.finfo(float).eps:raise GeometryError('stored centre is not a unit direction')
            out=cls(sphere,tuple(c),desc['min_cosine'])
            axis=np.eye(3)[int(np.argmin(np.abs(c)))];e=np.cross(axis,c)
            e/=np.linalg.norm(e);n=np.cross(c,e)
            object.__setattr__(out,'centre',tuple(float(x) for x in c))
            object.__setattr__(out,'_basis',np.array([e,n,c]).tobytes())
            if out.descriptor()!=desc:raise GeometryError('chart metadata mismatch')
            return out
        except (TypeError,KeyError) as exc:raise GeometryError('invalid chart metadata') from exc

    def __reduce__(self):return (_restore_chart,(self.descriptor(),))
    def __deepcopy__(self,memo):memo[id(self)]=self;return self

    @property
    def basis(self):return np.frombuffer(self._basis,dtype=np.float64).reshape(3,3)
    def descriptor(self):
        return {'schema':'atlas.gnomonic-chart.v1','sphere':self.sphere.descriptor(),
                'centre':list(self.centre),'min_cosine':self.min_cosine}
    @property
    def identity(self):return hashlib.sha256(_json(self.descriptor())).hexdigest()

    def _project(self, unit):
        local=unit@self.basis.T
        if np.any(local[...,2]<self.min_cosine):
            raise GeometryError('feature crosses chart horizon/conditioning limit; use explicit patches')
        return local[...,:2]/local[...,2,None]

    def _unproject(self, xy):
        # Scale before normalisation, including very large projected coordinates.
        xyz=np.concatenate((xy,np.ones((*xy.shape[:-1],1))),axis=-1)
        xyz/=np.max(np.abs(xyz),axis=-1,keepdims=True)
        xyz/=np.sqrt(np.sum(xyz*xyz,axis=-1,keepdims=True))
        return xyz@self.basis


def _restore_chart(desc):
    return SphericalChart.from_descriptor(desc)


def _rings(g):
    """Yield directed coordinate sequences; polygon holes remain separately tagged."""
    if g.is_empty:return
    if g.geom_type=='Polygon':
        yield np.asarray(g.exterior.coords),1
        for h in g.interiors:yield np.asarray(h.coords),-1
    elif g.geom_type in ('LineString','Point'):
        yield np.asarray(g.coords),0
    else:
        for part in g.geoms:yield from _rings(part)


def _ring_area(unit, anchor):
    pieces=[]
    for a,b in zip(unit[:-1],unit[1:]):
        # Translation inside the determinant avoids subtracting O(1) terms for
        # tiny regions. Signed fans also work for concave rings and exterior anchors.
        numerator=float(np.dot(anchor,np.cross(a-anchor,b-anchor)))
        denominator=1+float(np.dot(anchor,a))+float(np.dot(a,b))+float(np.dot(b,anchor))
        pieces.append(2*math.atan2(numerator,denominator))
    return abs(math.fsum(pieces))


@dataclass(frozen=True,slots=True,init=False)
class SphericalGeometry:
    chart: SphericalChart
    geometry_id: str
    _projected: PlanarGeometry=field(repr=False,compare=False)
    _segments_start: bytes=field(repr=False,compare=False)
    _segments_end: bytes=field(repr=False,compare=False)
    _area_sr: float=field(repr=False,compare=False)
    _length_rad: float=field(repr=False,compare=False)

    def __init__(self,*args,**kwargs):
        raise GeometryError('use polygon(), polyline() or from_projected_wkb()')

    @classmethod
    def _from_shape(cls,g,chart,*,limits=None):
        if type(chart) is not SphericalChart:raise GeometryError('SphericalChart required')
        limits=_limits(limits);_validate_shape(g,limits)
        xy=shapely.get_coordinates(g)
        if len(xy):
            unit=chart._unproject(xy)
            # A small rounding allowance applies to re-reading the declared chart,
            # not to moving its horizon or changing any feature coordinates.
            if np.any(unit@np.asarray(chart.centre)<chart.min_cosine*(1-32*np.finfo(float).eps)):
                raise GeometryError('stored geometry exceeds chart conditioning limit')
        starts=[];ends=[];areas=[];lengths=[]
        for coords,role in _rings(g):
            u=chart._unproject(coords)
            if len(u)==1:
                starts.append(u[0]);ends.append(u[0])
            else:
                for a,b in zip(u[:-1],u[1:]):
                    theta=2*math.atan2(float(np.linalg.norm(a-b)),float(np.linalg.norm(a+b)))
                    if theta==0 or theta>=math.pi:
                        raise GeometryError('degenerate or antipodal spherical edge')
                    starts.append(a);ends.append(b);lengths.append(theta)
            if role:areas.append(role*_ring_area(u,np.asarray(chart.centre)))
        area=math.fsum(areas);length=math.fsum(lengths)
        if g.geom_type in ('Polygon','MultiPolygon') and not g.is_empty and area<=0:
            raise GeometryError('spherical area is numerically unresolvable')
        if area<0 or not math.isfinite(area) or not math.isfinite(length):
            raise GeometryError('invalid spherical measure')
        if not math.isfinite((area*chart.sphere.radius_m)*chart.sphere.radius_m) or not math.isfinite(length*chart.sphere.radius_m):
            raise GeometryError('spherical metric exceeds binary64 range')
        projected=PlanarGeometry._from_shape(g,chart.identity,limits=limits)
        obj=object.__new__(cls)
        for key,value in [('chart',chart),('_projected',projected),('_area_sr',area),('_length_rad',length),
                ('_segments_start',np.asarray(starts,dtype=np.float64).reshape(-1,3).tobytes()),
                ('_segments_end',np.asarray(ends,dtype=np.float64).reshape(-1,3).tobytes())]:
            object.__setattr__(obj,key,value)
        ident=hashlib.sha256(_json({'schema':_SCHEMA_SPHERE,'chart':chart.descriptor()})+b'\0'+projected.wkb).hexdigest()
        object.__setattr__(obj,'geometry_id',ident)
        return obj

    @classmethod
    def polygon(cls,directions,*,holes=(),chart,limits=None,budget=None):
        """Concave/convex minor-arc polygon, optionally holed, inside one chart.

        Input triples are directions in the sphere's named axes. Magnitude is not
        altitude. Use stage-1 conversions with explicit angular units beforehand.
        """
        if type(chart) is not SphericalChart:raise GeometryError('SphericalChart required')
        if type(holes) not in (tuple,list):raise GeometryError('explicit holes sequence required')
        limits=_limits(limits);count=_preflight_vertices((directions,*holes),3,limits)
        with select_budget(budget).reserve(1024*count+16384,category='spherical-build'):
            outer=chart._project(_directions(_vertices(directions,3,ring=True,limits=limits)))
            inner=[chart._project(_directions(_vertices(h,3,ring=True,limits=limits))) for h in holes]
            planar=PlanarGeometry.polygon(outer,holes=inner,frame_id=chart.identity,limits=limits,budget=budget)
            return cls._from_shape(planar._geom,chart,limits=limits)

    @classmethod
    def polyline(cls,directions,*,chart,limits=None,budget=None):
        if type(chart) is not SphericalChart:raise GeometryError('SphericalChart required')
        limits=_limits(limits);count=_preflight_vertices((directions,),3,limits)
        with select_budget(budget).reserve(1024*count+16384,category='spherical-build'):
            xy=chart._project(_directions(_vertices(directions,3,ring=False,limits=limits)))
            p=PlanarGeometry.polyline(xy,frame_id=chart.identity,limits=limits,budget=budget)
            return cls._from_shape(p._geom,chart,limits=limits)

    @classmethod
    def from_projected_wkb(cls,raw,*,chart,limits=None,budget=None):
        p=PlanarGeometry.from_wkb(raw,frame_id=chart.identity,limits=limits,budget=budget)
        return cls._from_shape(p._geom,chart,limits=limits)

    @property
    def kind(self):return self._projected.kind
    @property
    def is_empty(self):return self._projected.is_empty
    @property
    def area_m2(self):return (self._area_sr*self.chart.sphere.radius_m)*self.chart.sphere.radius_m
    @property
    def length_m(self):return self._length_rad*self.chart.sphere.radius_m
    @property
    def area_steradians(self):return self._area_sr
    @property
    def vertex_count(self):return self._projected.vertex_count
    @property
    def retained_bytes(self):return self._projected.retained_bytes+len(self._segments_start)+len(self._segments_end)
    def descriptor(self):
        return {'schema':_SCHEMA_SPHERE,'space':'sphere-minor-arcs','chart':self.chart.descriptor(),
                'kind':self.kind,'geometry_id':self.geometry_id}

    def _distances(self,p):
        try:
            from ._geometry_native import arc_distances
        except ImportError as exc:
            raise GeometryError('native spherical distances require the declared Numba dependency') from exc
        starts=np.frombuffer(self._segments_start,dtype=np.float64).reshape(-1,3)
        ends=np.frombuffer(self._segments_end,dtype=np.float64).reshape(-1,3)
        if len(starts)==0:raise GeometryError('distance to empty geometry is undefined')
        return arc_distances(p,starts,ends)

    def classify(self,directions,*,angular_tolerance_rad=_DEFAULT_ANGULAR_BAND,
                 limits=None,budget=None,cancel=None):
        """-1 outside, +1 interior, 0 boundary/numerical band on the sphere.

        The default 64-epsilon angular band reports ambiguity; it does not move
        edges or select ownership. Explicit zero asks for raw projected predicates.
        Back-hemisphere queries are outside, not mirror-projected into the polygon.
        """
        # Empty geometry is still a query: honour cancellation before allocation
        # and again before its early publication, just as for nonempty batches.
        _check_cancel(cancel)
        limits=_limits(limits);shape=_point_shape(directions,3);n=elements(shape)//3
        tol=scalar(angular_tolerance_rad,'angular tolerance',nonnegative=True)
        if tol>=self.chart.min_cosine/4:raise GeometryError('boundary band exceeds chart validity allowance')
        with select_budget(budget).reserve(64*n+1024*min(n,limits.batch_points)+16384,category='spherical-query'):
            p=_directions(directions).reshape(-1,3);out=np.full(n,-1,dtype='i1')
            if self.is_empty:
                _check_cancel(cancel)
                return _typed_frozen(out.reshape(shape[:-1]),np.int8)
            shape_g=self._projected._geom
            boundary=self._projected._boundary_geom
            for start in range(0,n,limits.batch_points):
                _check_cancel(cancel);a=p[start:start+limits.batch_points];local=a@self.chart.basis.T
                visible=local[:,2]>=self.chart.min_cosine/2
                if not visible.any():continue
                indices=np.flatnonzero(visible);xy=local[visible,:2]/local[visible,2,None]
                q=shapely.points(xy)
                inside=shapely.contains(self._projected._area_geom,q)
                covered=shapely.intersects(shape_g,q)
                result=np.where(inside,1,np.where(covered,0,-1)).astype('i1')
                if tol:
                    # Gnomonic derivative <= 1/cos^2. Use a conservative broad
                    # phase, then measure actual minor-arc distance for the band.
                    near=shapely.distance(boundary,q)<=8*tol/self.chart.min_cosine**2
                    if near.any():result[near]=np.where(self._distances(a[visible][near])<=tol,0,result[near])
                out[start+indices]=result
            _check_cancel(cancel)
            return _typed_frozen(out.reshape(shape[:-1]),np.int8)

    def distance_to(self,directions,*,boundary=False,limits=None,budget=None,cancel=None):
        """Great-circle metres to finite arcs, not to their infinite great circles."""
        if type(boundary) is not bool:raise GeometryError('boundary must be bool')
        if self.is_empty:raise GeometryError('distance to empty geometry is undefined')
        limits=_limits(limits);shape=_point_shape(directions,3);n=elements(shape)//3
        with select_budget(budget).reserve(80*n+1024*min(n,limits.batch_points)+16384,category='spherical-distance'):
            p=_directions(directions).reshape(-1,3);out=np.empty(n)
            for start in range(0,n,limits.batch_points):
                _check_cancel(cancel);a=p[start:start+limits.batch_points]
                distances=self._distances(a)
                if not boundary and self._area_sr>0:
                    inside=self.classify(a,angular_tolerance_rad=0,limits=limits,budget=budget,cancel=cancel)>=0
                    distances[inside]=0
                # Finite radians do not guarantee representable metres. Decide
                # region-interior zero first, then reject overflow at the API
                # boundary rather than publishing inf as a physical distance.
                with np.errstate(over='ignore', invalid='ignore'):
                    distances *= self.chart.sphere.radius_m
                if not np.isfinite(distances).all():
                    raise GeometryError('spherical distance exceeds binary64 range')
                out[start:start+len(a)]=distances
            _check_cancel(cancel)
            return _typed_frozen(out.reshape(shape[:-1]),np.float64)

    def within_distance(self,directions,half_width_m,**kwargs):
        width=scalar(half_width_m,'half width',nonnegative=True)
        return _typed_frozen(self.distance_to(directions,**kwargs)<=width,np.bool_)

    def in_chart(self,chart,*,limits=None,budget=None):
        if type(chart) is not SphericalChart or chart.sphere!=self.chart.sphere:
            raise GeometryError('spherical frame/radius mismatch')
        if chart.identity==self.chart.identity:return self
        limits=_limits(limits)
        with select_budget(budget).reserve(1024*self.vertex_count+16384,category='spherical-rechart'):
            def project(xy):return chart._project(self.chart._unproject(xy))
            try:g=shapely.transform(self._projected._geom,project)
            except GEOSException as exc:raise GeometryError('spherical rechart failed') from exc
            return type(self)._from_shape(g,chart,limits=limits)

    def overlay(self,other,operation='intersection',*,limits=None,budget=None,cancel=None):
        if type(other) is not SphericalGeometry or other.chart.sphere!=self.chart.sphere:
            raise GeometryError('spherical frame/radius mismatch')
        if operation not in ('intersection','union','difference','symmetric_difference'):
            raise GeometryError('unsupported geometry operation')
        _check_cancel(cancel);limits=_limits(limits)
        if self.geometry_id==other.geometry_id:
            if self.vertex_count>limits.max_vertices:raise GeometryError('geometry vertex limit exceeded')
            if operation in ('intersection','union'):return self
            from shapely.geometry import GeometryCollection
            return type(self)._from_shape(GeometryCollection(),self.chart,limits=limits)
        # Try the existing charts before preparing a joint chart. No latitude seam
        # splitting or great-circle densification is needed for an admissible pair.
        a,b=self,None
        try:b=other.in_chart(self.chart,limits=limits,budget=budget)
        except GeometryError:
            try:a=self.in_chart(other.chart,limits=limits,budget=budget);b=other
            except GeometryError:
                points=np.vstack((self.chart._unproject(shapely.get_coordinates(self._projected._geom)),
                                  other.chart._unproject(shapely.get_coordinates(other._projected._geom))))
                centre=np.sum(points,axis=0)
                if not len(points) or np.linalg.norm(centre)==0:
                    raise GeometryError('no supported common hemisphere; split the operation into explicit patches')
                joint=SphericalChart(self.chart.sphere,tuple(centre),max(self.chart.min_cosine,other.chart.min_cosine))
                a=self.in_chart(joint,limits=limits,budget=budget);b=other.in_chart(joint,limits=limits,budget=budget)
        with _overlay_budget(a._projected._geom,b._projected._geom,limits,budget):
            try:g=getattr(shapely,operation)(a._projected._geom,b._projected._geom,grid_size=0.)
            except GEOSException as exc:raise GeometryError('spherical overlay failed; no repair attempted') from exc
            _check_cancel(cancel)
            return type(self)._from_shape(g,a.chart,limits=limits)

    def __reduce__(self):return (_restore_spherical,(self._projected.wkb,self.chart,self.geometry_id))
    def __deepcopy__(self,memo):memo[id(self)]=self;return self


def _restore_spherical(raw,chart,expected):
    out=SphericalGeometry.from_projected_wkb(raw,chart=chart)
    if out.geometry_id!=expected:raise GeometryError('restored spherical identity mismatch')
    return out
