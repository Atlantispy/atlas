"""Reusable spatial candidate pruning, coverage diagnostics and geometry persistence.

The index returns ALL matching features in stable ID order. It never resolves an
ambiguous plate owner, erases overlap or turns missing coverage into empty geology.
Spherical features are grouped by conditioned chart; bounding boxes are used only
for pruning, with final predicates/metric boundary-band tests in each chart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

import numpy as np
import shapely
from shapely.geometry import GeometryCollection
from shapely.strtree import STRtree

from .geometry import (PlanarGeometry, GeometryError, GeometryLimits, _limits, _label,
    _json, _point_shape, _typed_frozen, _check_cancel)
from .spherical_geometry import SphericalGeometry, SphericalChart, _directions, _DEFAULT_ANGULAR_BAND
from .coordinates import SphericalFrame
from ._validation import read_array, scalar
from .resources import elements, select_budget


@dataclass(frozen=True,slots=True)
class GeometryFeature:
    feature_id: str
    geometry: PlanarGeometry | SphericalGeometry

    def __post_init__(self):
        _label(self.feature_id,'feature ID')
        if type(self.geometry) not in (PlanarGeometry,SphericalGeometry):
            raise GeometryError('supported immutable geometry required')
        if self.geometry.is_empty:raise GeometryError('empty feature cannot be indexed')


def _parts(g):
    # Splitting a multipart envelope improves broad-phase selectivity. It does NOT
    # create new geological features or discard holes/contacts inside each part.
    if g.geom_type in ('Polygon','LineString','Point'):
        yield g
    else:
        for item in g.geoms:yield from _parts(item)


@dataclass(frozen=True,slots=True)
class GeometryHits:
    feature_ids: tuple[str,...]
    candidate_pairs: int
    exhaustive_pairs: int
    _payload: bytes=field(repr=False)
    @property
    def pairs(self):
        """Read-only (query-flat-index, feature-index) rows, lexically sorted."""
        return np.frombuffer(self._payload,dtype=np.int64).reshape(-1,2)


class GeometryIndex:
    """Caller-owned STRtrees with shared immutable feature definitions.

    The retained native-index allowance is held until close(). It is an estimate,
    not a hard GEOS heap cap. Owner-held geometry payloads are counted separately.
    Read queries are safe to run concurrently; close only after joining readers.
    Query batches bound native candidate arrays and total output is limited.
    """
    def __setattr__(self, name, value):
        if name in ('features','feature_ids','limits','budget','spherical','identity') and hasattr(self,name):
            raise GeometryError('indexed scientific inputs are immutable; build a new index')
        object.__setattr__(self,name,value)

    def __init__(self,features,*,limits=None,budget=None):
        import threading
        if type(features) not in (tuple,list) or not features or any(type(f) is not GeometryFeature for f in features):
            raise GeometryError('nonempty explicit GeometryFeature sequence required')
        self.features=tuple(sorted(features,key=lambda f:f.feature_id))
        ids=tuple(f.feature_id for f in self.features)
        if len(set(ids))!=len(ids):raise GeometryError('duplicate feature ID')
        self.limits=_limits(limits);self.budget=select_budget(budget)
        self.feature_ids=ids;first=self.features[0].geometry
        self.spherical=type(first) is SphericalGeometry
        if any(type(f.geometry) is not type(first) for f in self.features):
            raise GeometryError('planar and spherical features cannot share an index')
        for f in self.features:
            if self.spherical:
                if f.geometry.chart.sphere!=first.chart.sphere:raise GeometryError('index sphere/frame mismatch')
            elif f.geometry.frame_id!=first.frame_id:raise GeometryError('index planar frame mismatch')
        vertices=sum(f.geometry.vertex_count for f in self.features)
        if vertices>self.limits.max_vertices:raise GeometryError('index vertex budget exceeded')
        self._guard=self.budget.reserve(512*vertices+2048*len(features)+16384,category='geometry-index-retained')
        self._guard.__enter__()
        self._lock=threading.Lock();self._active=0;self._closed=False
        try:
            self._groups=[];grouped={}
            for i,f in enumerate(self.features):
                g=f.geometry;chart=g.chart if self.spherical else None
                key=chart.identity if chart else first.frame_id
                if key not in grouped:grouped[key]=(chart,[],[])
                _,shapes,owners=grouped[key]
                for part in _parts(g._projected._geom if self.spherical else g._geom):
                    shapes.append(part);owners.append(i)
            for key,(chart,shapes,owners) in sorted(grouped.items()):
                if len(shapes)>self.limits.max_hits:raise GeometryError('index entry count exceeds query envelope')
                self._groups.append((chart,STRtree(shapes),np.asarray(owners,dtype=np.int64),len(shapes)))
            self.identity=hashlib.sha256(_json({'schema':'atlas.geometry-index.v1',
                'features':[(f.feature_id,f.geometry.geometry_id) for f in self.features]})).hexdigest()
        except BaseException:
            self._guard.__exit__(None,None,None);raise

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        with self._lock:
            if self._active:raise GeometryError('join active geometry queries before closing index')
            if not self._closed:
                self._groups.clear();self._closed=True;self._guard.__exit__(None,None,None)

    def query(self,points,*,angular_tolerance_rad=_DEFAULT_ANGULAR_BAND,budget=None,cancel=None):
        """Return all region/trace matches, including every boundary owner candidate.

        Spherical numerical bands use a conservative projected envelope followed
        by true finite-arc distance tests. No nearest-only or first-hit tie break.
        Use query_batches() to avoid retaining an entire world's match table.
        """
        with self._lock:
            if self._closed:raise GeometryError('geometry index is closed')
            self._active+=1
        try:
            dim=3 if self.spherical else 2;shape=_point_shape(points,dim);n=elements(shape)//dim
            tol=scalar(angular_tolerance_rad,'angular tolerance',nonnegative=True)
            maximum=min(n*len(self.features),self.limits.max_hits)
            groups=list(self._groups);batch=min(self.limits.batch_points,
                max(1,self.limits.max_hits//max(g[3] for g in groups)))
            # Native result capacity, snapshots and concatenation are all charged.
            required=64*maximum+64*n+1024*batch+16384
            policy=self.budget if budget is None else select_budget(budget)
            from .resources import reserve_budgets
            with reserve_budgets(required,self.budget,policy,category='geometry-index-query'):
                p=(_directions(points) if self.spherical else read_array(points,'points')).reshape(-1,dim)
                rows=[];candidate_count=0;hit_count=0
                for start in range(0,n,batch):
                    _check_cancel(cancel);part=p[start:start+batch]
                    for chart,tree,owners,entries in groups:
                        if chart:
                            if tol>=chart.min_cosine/4:raise GeometryError('query band outside chart validity')
                            local=part@chart.basis.T;valid=np.flatnonzero(local[:,2]>=chart.min_cosine/2)
                            if not len(valid):continue
                            xy=local[valid,:2]/local[valid,2,None]
                            margin=8*tol/chart.min_cosine**2
                            query=shapely.box(xy[:,0]-margin,xy[:,1]-margin,xy[:,0]+margin,xy[:,1]+margin) if tol else shapely.points(xy)
                            candidates=tree.query(query)
                        else:
                            valid=np.arange(len(part));query=shapely.points(part);candidates=tree.query(query)
                        candidate_count+=candidates.shape[1]
                        if not candidates.size:continue
                        if chart is None:
                            exact=shapely.intersects(tree.geometries.take(candidates[1]),query.take(candidates[0]))
                            candidates=candidates[:,exact]
                            if not candidates.size:continue
                        pairs=np.column_stack((valid[candidates[0]],owners[candidates[1]]))
                        pairs=np.unique(pairs,axis=0)
                        if chart:
                            keep=np.empty(len(pairs),dtype=bool)
                            for feature in np.unique(pairs[:,1]):
                                selected=pairs[:,1]==feature
                                keep[selected]=self.features[int(feature)].geometry.classify(
                                    part[pairs[selected,0]],angular_tolerance_rad=tol,
                                    limits=self.limits,budget=policy,cancel=cancel)>=0
                            pairs=pairs[keep]
                        pairs[:,0]+=start
                        hit_count+=len(pairs)
                        if hit_count>self.limits.max_hits:raise GeometryError('query result exceeds max_hits; consume smaller batches')
                        rows.append(pairs)
                if rows:
                    result=np.unique(np.concatenate(rows),axis=0)
                else:result=np.empty((0,2),dtype=np.int64)
                _check_cancel(cancel)
                return GeometryHits(self.feature_ids,candidate_count,n*len(self.features),result.astype(np.int64).tobytes())
        finally:
            with self._lock:self._active-=1

    def query_batches(self,batches,**kwargs):
        for batch in batches:yield self.query(batch,**kwargs)


@dataclass(frozen=True,slots=True)
class CoverageReport:
    """Geometric coverage evidence, not repaired geometry or a topology assignment."""
    domain_id: str
    feature_ids: tuple[str,...]
    gaps: Any
    outside: Any
    overlaps: tuple  # (ID, ID, positive-area geometry), pairwise not union-counted
    contacts: tuple  # zero-area intersections retained separately
    @property
    def complete(self):return self.gaps.is_empty and self.outside.is_empty and not self.overlaps
    @property
    def gap_area_m2(self):return self.gaps.area_m2
    @property
    def outside_area_m2(self):return self.outside.area_m2


def audit_coverage(domain,features,*,limits=None,budget=None,cancel=None):
    """Expose gaps, outside coverage, overlaps and contacts without silent repair.

    This initial-domain audit is not W01 stage-3 shared-edge/junction construction.
    For spherical coverage, all regions must fit the declared domain chart; global
    patch-seam reconciliation is deliberately not inferred from a planar union.
    """
    if type(domain) not in (PlanarGeometry,SphericalGeometry) or domain.kind not in ('Polygon','MultiPolygon') or domain.is_empty:
        raise GeometryError('nonempty polygonal domain required')
    if type(features) not in (tuple,list) or not features or any(type(f) is not GeometryFeature for f in features):
        raise GeometryError('explicit nonempty region features required')
    features=tuple(sorted(features,key=lambda x:x.feature_id));limits=_limits(limits)
    if len(set(f.feature_id for f in features))!=len(features):raise GeometryError('duplicate region ID')
    count=sum(f.geometry.vertex_count for f in features)
    if count>limits.max_vertices or len(features)**2>limits.max_overlay_pairs:
        raise GeometryError('coverage envelope exceeds configured limit')
    with select_budget(budget).reserve(1024*count+65536,category='coverage-audit'):
        prepared=[]
        for f in features:
            if type(f.geometry) is not type(domain) or f.geometry.kind not in ('Polygon','MultiPolygon'):
                raise GeometryError('coverage members must be regions in the same space')
            g=f.geometry.in_chart(domain.chart,limits=limits,budget=budget) if type(domain) is SphericalGeometry else f.geometry
            if type(domain) is PlanarGeometry and g.frame_id!=domain.frame_id:raise GeometryError('coverage frame mismatch')
            prepared.append(GeometryFeature(f.feature_id,g))
        total=prepared[0].geometry;overlaps=[];contacts=[]
        # Polygon-envelope pruning, not blind O(F^2) exact intersections.
        shapes=[f.geometry._projected._geom if type(domain) is SphericalGeometry else f.geometry._geom for f in prepared]
        tree=STRtree(shapes)
        for i,f in enumerate(prepared):
            _check_cancel(cancel)
            for j in sorted(int(x) for x in tree.query(shapes[i]) if x>i):
                inter=f.geometry.overlay(prepared[j].geometry,limits=limits,budget=budget,cancel=cancel)
                if not inter.is_empty:
                    row=(f.feature_id,prepared[j].feature_id,inter)
                    (overlaps if inter.area_m2>0 else contacts).append(row)
            if i:total=total.overlay(f.geometry,'union',limits=limits,budget=budget,cancel=cancel)
        gaps=domain.overlay(total,'difference',limits=limits,budget=budget,cancel=cancel)
        outside=total.overlay(domain,'difference',limits=limits,budget=budget,cancel=cancel)
        return CoverageReport(domain.geometry_id,tuple(f.feature_id for f in prepared),gaps,outside,tuple(overlaps),tuple(contacts))


def save_geometry(geometry,store,*,budget=None,cancel=None):
    """Persist immutable definitions in the existing deduplicated array store.

    Prepared native objects and indexes are NOT pickled or assumed valid on reload.
    The next load rebuilds and validates geometry from its identified bytes.
    """
    from .storage import ArrayStore
    if type(geometry) not in (PlanarGeometry,SphericalGeometry) or not isinstance(store,ArrayStore):
        raise GeometryError('typed geometry and existing ArrayStore required')
    raw=geometry.wkb if type(geometry) is PlanarGeometry else geometry._projected.wkb
    return store.put(geometry.geometry_id,{'geometry_wkb':np.frombuffer(raw,dtype='u1')},
                     geometry.descriptor(),budget=budget,cancel=cancel)


def load_geometry(store,geometry_id,*,limits=None,budget=None):
    values=store.get(geometry_id,budget=budget)
    if values is None:return None
    meta=store.metadata(geometry_id)
    if (set(values)!={'geometry_wkb'} or values['geometry_wkb'].dtype!=np.dtype('u1')
            or values['geometry_wkb'].ndim!=1 or type(meta) is not dict):
        raise GeometryError('invalid saved geometry inventory')
    raw=values['geometry_wkb'].tobytes();space=meta.get('space')
    try:
        if space=='planar-metres':
            out=PlanarGeometry.from_wkb(raw,frame_id=meta['frame_id'],limits=limits,budget=budget)
        elif space=='sphere-minor-arcs':
            desc=meta['chart']
            chart=SphericalChart.from_descriptor(desc)
            if chart.descriptor()!=desc:raise GeometryError('stored spherical chart mismatch')
            out=SphericalGeometry.from_projected_wkb(raw,chart=chart,limits=limits,budget=budget)
        else:raise GeometryError('unsupported saved geometry space')
        if out.geometry_id!=geometry_id or out.descriptor()!=meta:raise GeometryError('saved geometry identity mismatch')
        return out
    except (KeyError,TypeError,ValueError) as exc:
        raise GeometryError('invalid geometry snapshot') from exc
