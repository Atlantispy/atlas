"""W01 stage 2: immutable planar feature geometry with explicit frames and limits.

GEOS supplies robust double-precision planar predicates/overlays through Shapely.
No make_valid, snapping, buffering-to-repair or tolerance-driven deletion occurs.
Polygons describe occupied area; polylines describe zero-width fault/feature traces.
A distance query can describe a weak-zone corridor without polygonising a circle.
Authored polygon holes must not touch. Overlays and WKB restoration retain valid
point-touching holes produced by set operations, subject to structural validation.

Coordinates are metres in an identified Cartesian plane, NOT longitude/latitude.
The geometry does not assign plate ownership or decide which overlapping feature
wins: those are subsequent topology and geological-case responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import json
import math
import struct

import numpy as np
import shapely
from shapely.errors import GEOSException
from shapely.geometry import Polygon, LineString, GeometryCollection

from ._validation import TectonicsError, input_shape, read_array, scalar
from .coordinates import _label
from .resources import elements, select_budget


class GeometryError(TectonicsError):
    """Invalid, incompatible, ambiguous or numerically unsupported geometry."""


@dataclass(frozen=True, slots=True)
class GeometryLimits:
    """Overridable execution limits, not resolution or geological constants.

    GEOS allocates internally. Reservations below are conservative admission
    estimates, not enforcement of its heap or a process-wide memory limit.
    """
    max_vertices: int = 100_000
    max_overlay_pairs: int = 1_000_000
    max_hits: int = 1_000_000
    batch_points: int = 4096

    def __post_init__(self):
        for key in ('max_vertices', 'max_overlay_pairs', 'max_hits', 'batch_points'):
            value = getattr(self, key)
            if type(value) is not int or value <= 0:
                raise GeometryError(key+' must be a positive integer')


DEFAULT_GEOMETRY_LIMITS = GeometryLimits()
_SCHEMA = 'atlas.feature-geometry.v1'


def _limits(value):
    if value is None:
        return DEFAULT_GEOMETRY_LIMITS
    if type(value) is not GeometryLimits:
        raise GeometryError('explicit GeometryLimits required')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _typed_frozen(value, dtype):
    a = np.asarray(value, dtype=dtype, order='C')
    return np.frombuffer(a.tobytes(), dtype=dtype).reshape(a.shape)


def _check_cancel(cancel):
    from concurrent.futures import CancelledError
    if cancel is not None:
        if not callable(getattr(cancel, 'is_set', None)):
            raise GeometryError('cancel must provide is_set()')
        if cancel.is_set():
            raise CancelledError('geometry operation cancelled')


def _point_shape(value, dimensions):
    shape = input_shape(value, 'query coordinates')
    if not shape or shape[-1] != dimensions or elements(shape) == 0:
        raise GeometryError(f'nonempty (...,{dimensions}) coordinates required')
    return shape


def _vertices(value, dimensions, *, ring, limits):
    shape = _point_shape(value, dimensions)
    if len(shape) != 2 or shape[0] > limits.max_vertices:
        raise GeometryError('vertex matrix or vertex limit invalid')
    a = read_array(value, 'feature vertices')
    # Accept the conventional repeated closing endpoint, but no other duplicates.
    if ring and len(a) > 1 and np.array_equal(a[0], a[-1]):
        a = a[:-1]
    if len(a) < (3 if ring else 2):
        raise GeometryError('insufficient feature vertices')
    if np.any(np.all(a[1:] == a[:-1], axis=1)):
        raise GeometryError('zero-length edge')
    if ring and len(np.unique(a, axis=0)) != len(a):
        raise GeometryError('polygon ring repeats a vertex')
    return a


def _preflight_vertices(values, dimensions, limits):
    total = 0
    for value in values:
        shape = _point_shape(value, dimensions)
        if len(shape) != 2:
            raise GeometryError('vertices must be a two-dimensional matrix')
        total += shape[0]
    if total > limits.max_vertices:
        raise GeometryError('geometry vertex limit exceeded')
    return total


def _inspect_wkb(raw, limits):
    """Check type/count/length envelopes before GEOS sees a binary definition.

    A tiny corrupt payload must not request billions of native points/rings. Only
    standard 2D WKB types 1-7 are supported; EWKB/SRID/Z/M need an explicit importer.
    This parser does not repair topology. GEOS still validates the actual shape.
    """
    offset=0;vertices=0;parts=0;pending=[(None,0)]
    def count_at(position,endian):
        if position+4>len(raw):raise GeometryError('truncated WKB count')
        return struct.unpack_from(endian+'I',raw,position)[0],position+4
    while pending:
        expected,depth=pending.pop();parts+=1
        if depth>64 or parts>limits.max_vertices+1 or offset+5>len(raw):
            raise GeometryError('WKB nesting/part/length envelope exceeded')
        order=raw[offset]
        if order not in (0,1):raise GeometryError('invalid WKB byte order')
        endian='<' if order else '>'
        kind=struct.unpack_from(endian+'I',raw,offset+1)[0];offset+=5
        if kind not in range(1,8) or expected is not None and kind!=expected:
            raise GeometryError('unsupported WKB type/dimensionality')
        if kind==1:
            vertices+=1;offset+=16
        elif kind in (2,3):
            rings=1
            if kind==3:
                rings,offset=count_at(offset,endian)
                if rings>limits.max_vertices:raise GeometryError('WKB ring count exceeds limit')
            for _ in range(rings):
                count,offset=count_at(offset,endian)
                vertices+=count
                if vertices>limits.max_vertices or count>(len(raw)-offset)//16:
                    raise GeometryError('WKB coordinate count exceeds payload or limit')
                offset+=16*count
        else:
            count,offset=count_at(offset,endian)
            if count>limits.max_vertices or count>(len(raw)-offset)//5:
                raise GeometryError('WKB child count exceeds payload or limit')
            expected_child={4:1,5:2,6:3,7:None}[kind]
            pending.extend((expected_child,depth+1) for _ in range(count))
        if offset>len(raw) or vertices>limits.max_vertices:
            raise GeometryError('WKB coordinate envelope exceeded')
    if offset!=len(raw):raise GeometryError('WKB trailing bytes are not part of geometry')


def _validate_shape(g, limits, *, allow_empty=True):
    if g is None or shapely.has_z(g) or shapely.has_m(g):
        raise GeometryError('only explicit two-dimensional geometry supported')
    n = int(shapely.get_num_coordinates(g))
    if n > limits.max_vertices:
        raise GeometryError('result exceeds geometry vertex limit')
    if g.is_empty:
        if not allow_empty:
            raise GeometryError('empty input feature')
        return
    xy = shapely.get_coordinates(g)
    if not np.isfinite(xy).all():
        raise GeometryError('nonfinite geometry coordinates')
    if not shapely.is_valid(g):
        raise GeometryError('invalid geometry: '+str(shapely.is_valid_reason(g)))
    # GEOS validity does not reject an adjacent repeated coordinate. Apply the
    # same sequence rules to WKB/imported/overlay shapes as to direct builders;
    # otherwise restoration can bypass the no-zero-length-edge contract.
    if g.geom_type == 'Polygon':
        _vertices(np.asarray(g.exterior.coords), 2, ring=True, limits=limits)
        for ring in g.interiors:
            _vertices(np.asarray(ring.coords), 2, ring=True, limits=limits)
    elif g.geom_type in ('LineString', 'LinearRing'):
        _vertices(xy, 2, ring=g.geom_type == 'LinearRing', limits=limits)
    # A fault trace may not secretly self-cross. Explicitly node/split it instead.
    if g.geom_type in ('LineString', 'MultiLineString') and not shapely.is_simple(g):
        raise GeometryError('self-crossing/repeated trace; split the feature explicitly')
    if not math.isfinite(g.area) or not math.isfinite(g.length):
        raise GeometryError('geometry measure outside binary64 range')
    if g.geom_type in ('Polygon', 'MultiPolygon') and g.area <= 0:
        raise GeometryError('zero-area region')
    if g.geom_type in ('LineString', 'MultiLineString') and g.length <= 0:
        raise GeometryError('zero-length trace')
    if g.geom_type in ('GeometryCollection', 'MultiLineString', 'MultiPolygon'):
        for part in g.geoms:
            _validate_shape(part, limits)



def _measure_components(g):
    """Separate 2D interiors from lower-dimensional contacts without deleting either."""
    areas=[];edges=[]
    def visit(part):
        if part.is_empty:return
        if part.geom_type=='Polygon':
            areas.append(part);edges.append(part.boundary)
        elif part.geom_type in ('LineString','Point'):
            edges.append(part)
        else:
            for child in part.geoms:visit(child)
    visit(g)
    area=GeometryCollection(areas) if len(areas)!=1 else areas[0]
    boundary=GeometryCollection(edges) if len(edges)!=1 else edges[0]
    shapely.prepare(area)
    return area,boundary


def _overlay_budget(a, b, limits, budget):
    n, m = int(shapely.get_num_coordinates(a)), int(shapely.get_num_coordinates(b))
    # An overlay can produce O(n*m) intersections. Refuse before native allocation
    # when that envelope exceeds the case's explicit limit; do not downsample.
    separated = (not a.is_empty and not b.is_empty and
        (a.bounds[2] < b.bounds[0] or b.bounds[2] < a.bounds[0] or
         a.bounds[3] < b.bounds[1] or b.bounds[3] < a.bounds[1]))
    potential = 0 if separated else n*m
    if potential > limits.max_overlay_pairs:
        raise GeometryError('overlay intersection envelope exceeds limit; partition explicitly')
    return select_budget(budget).reserve(256*(n+m)+96*potential+16384,
                                         category='geometry-overlay')


@dataclass(frozen=True, slots=True, init=False)
class PlanarGeometry:
    """Prepared immutable geometry; construction captures caller coordinates once.

    WKB is the lossless retained definition. The cached GEOS representation and
    prepared search data are reconstructible. IDs describe geometry and frame,
    not material identity or a complete scientific execution receipt.
    """
    frame_id: str
    geometry_id: str
    _wkb: bytes = field(repr=False, compare=False)
    _geom: Any = field(repr=False, compare=False)
    _area_geom: Any = field(repr=False, compare=False)
    _boundary_geom: Any = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise GeometryError('use polygon(), polyline() or from_wkb()')

    @classmethod
    def _from_shape(cls, shape, frame_id, *, limits=None):
        _label(frame_id, 'planar frame'); limits = _limits(limits)
        _validate_shape(shape, limits)
        # Keep ring order and trace direction in the identity. Reversing a trace
        # must remain observable when W01 stage 3 assigns its sides.
        raw = bytes(shapely.to_wkb(shape, byte_order=1, output_dimension=2))
        obj = object.__new__(cls)
        object.__setattr__(obj, 'frame_id', frame_id)
        object.__setattr__(obj, '_wkb', raw)
        shapely.prepare(shape)
        object.__setattr__(obj, '_geom', shape)
        area_g, boundary_g = _measure_components(shape)
        object.__setattr__(obj, '_area_geom', area_g)
        object.__setattr__(obj, '_boundary_geom', boundary_g)
        object.__setattr__(obj, 'geometry_id', hashlib.sha256(
            _json({'schema':_SCHEMA, 'space':'planar-metres', 'frame_id':frame_id})+b'\0'+raw).hexdigest())
        return obj

    @classmethod
    def polygon(cls, exterior, *, holes=(), frame_id, limits=None, budget=None):
        """Simple concave/convex polygon with optional non-touching interior holes.

        Invalid holes, crossings, degeneracy and duplicate vertices are errors.
        Closing a ring does not change its vertices or make invalid input valid.
        Non-touching holes are an authoring restriction; overlays and WKB restore
        may retain valid point contacts without repairing or removing them.
        """
        limits = _limits(limits)
        if type(holes) not in (tuple, list):
            raise GeometryError('holes must be an explicit sequence')
        count = _preflight_vertices((exterior, *holes), 2, limits)
        with select_budget(budget).reserve(512*count+8192, category='geometry-build'):
            outer = _vertices(exterior, 2, ring=True, limits=limits)
            inner = [_vertices(h, 2, ring=True, limits=limits) for h in holes]
            shape = Polygon(outer, inner)
            _validate_shape(shape, limits, allow_empty=False)
            # GEOS allows point-touching holes in some valid configurations. This
            # authoring constructor chooses strictly interior, disjoint holes.
            shell = Polygon(outer)
            hole_shapes = [Polygon(h) for h in inner]
            if hole_shapes:
                # Reuse each hole geometry and a spatial index; do not rebuild
                # every preceding hole for an O(H^2) comparison loop.
                from shapely.strtree import STRtree
                hole_tree = STRtree(hole_shapes)
                for i, hp in enumerate(hole_shapes):
                    if not shell.contains(hp) or shell.boundary.intersects(hp):
                        raise GeometryError('hole must be strictly inside the shell')
                    if any(int(j) != i for j in hole_tree.query(hp, predicate='intersects')):
                        raise GeometryError('holes touch, overlap or nest')
            return cls._from_shape(shape, frame_id, limits=limits)

    @classmethod
    def polyline(cls, vertices, *, frame_id, limits=None, budget=None):
        limits = _limits(limits)
        count = _preflight_vertices((vertices,), 2, limits)
        with select_budget(budget).reserve(512*count+8192, category='geometry-build'):
            a = _vertices(vertices, 2, ring=False, limits=limits)
            shape = LineString(a); _validate_shape(shape, limits, allow_empty=False)
            return cls._from_shape(shape, frame_id, limits=limits)

    @classmethod
    def from_wkb(cls, raw, *, frame_id, limits=None, budget=None):
        """Restore validated geometry, including valid overlay point contacts.

        Uses the overlay-output contract, not polygon()'s stricter authored-hole
        rule, so storing an exact set operation does not change its admissibility.
        """
        limits = _limits(limits)
        if type(raw) is not bytes or len(raw) > 64*limits.max_vertices+4096:
            raise GeometryError('bounded immutable WKB bytes required')
        with select_budget(budget).reserve(32*len(raw)+8192, category='geometry-restore'):
            _inspect_wkb(raw,limits)
            try:
                return cls._from_shape(shapely.from_wkb(raw, on_invalid='raise'), frame_id, limits=limits)
            except (GEOSException, ValueError) as exc:
                raise GeometryError('invalid stored geometry') from exc

    @property
    def kind(self): return self._geom.geom_type
    @property
    def is_empty(self): return self._geom.is_empty
    @property
    def area_m2(self): return float(self._geom.area)
    @property
    def length_m(self): return float(self._geom.length)
    @property
    def bounds(self): return None if self.is_empty else tuple(self._geom.bounds)
    @property
    def wkb(self): return self._wkb
    @property
    def vertex_count(self): return int(shapely.get_num_coordinates(self._geom))
    @property
    def retained_bytes(self):
        """Definition bytes only; native GEOS/prepared-index memory is additional."""
        return len(self._wkb)

    def descriptor(self):
        return {'schema':_SCHEMA, 'space':'planar-metres', 'frame_id':self.frame_id,
                'kind':self.kind, 'geometry_id':self.geometry_id}

    def classify(self, points_m, *, boundary_tolerance_m=0., limits=None, budget=None, cancel=None):
        """Return int8 -1 outside, 0 boundary/boundary-band, +1 strict interior.

        A nonzero explicitly requested tolerance reports uncertainty near a boundary;
        it never snaps geometry or assigns a feature to one neighbouring plate.
        Traces have no areal interior. Empty geometry classifies everything outside.
        """
        limits=_limits(limits);shape=_point_shape(points_m,2);n=elements(shape)//2
        tol=scalar(boundary_tolerance_m,'boundary tolerance',nonnegative=True)
        with select_budget(budget).reserve(32*n+512*min(n,limits.batch_points)+8192,category='geometry-query'):
            points=read_array(points_m,'points').reshape(-1,2)
            out=np.full(n,-1,dtype='i1')
            boundary = self._boundary_geom
            for start in range(0,n,limits.batch_points):
                _check_cancel(cancel);a=points[start:start+limits.batch_points]
                query=shapely.points(a)
                inside=shapely.contains(self._area_geom,query)
                covered=shapely.intersects(self._geom,query)
                out[start:start+len(a)]=np.where(inside,1,np.where(covered,0,-1))
                if tol:
                    near=shapely.distance(boundary,query)<=tol
                    out[start:start+len(a)][near]=0
            _check_cancel(cancel)
            return _typed_frozen(out.reshape(shape[:-1]),np.int8)

    def distance_to(self, points_m, *, boundary=False, limits=None, budget=None, cancel=None):
        """Euclidean distance in metres; region interiors have distance zero.

        boundary=True measures to the perimeter instead. Empty distance is undefined
        and refused rather than emitted as NaN or guessed as zero.
        """
        if type(boundary) is not bool: raise GeometryError('boundary must be bool')
        if self.is_empty: raise GeometryError('distance to empty geometry is undefined')
        limits=_limits(limits);shape=_point_shape(points_m,2);n=elements(shape)//2
        g=self._boundary_geom if boundary else self._geom
        with select_budget(budget).reserve(48*n+512*min(n,limits.batch_points)+8192,category='geometry-distance'):
            p=read_array(points_m,'points').reshape(-1,2);out=np.empty(n)
            for start in range(0,n,limits.batch_points):
                _check_cancel(cancel);a=p[start:start+limits.batch_points]
                out[start:start+len(a)]=shapely.distance(g,shapely.points(a))
            if not np.isfinite(out).all():raise GeometryError('distance outside numerical range')
            _check_cancel(cancel)
            return _typed_frozen(out.reshape(shape[:-1]),np.float64)

    def within_distance(self, points_m, half_width_m, **kwargs):
        """Exact distance test for a trace corridor; no polygonal buffer approximation."""
        width=scalar(half_width_m,'corridor half width',nonnegative=True)
        return _typed_frozen(self.distance_to(points_m,**kwargs)<=width,np.bool_)

    def overlay(self, other, operation='intersection', *, limits=None, budget=None, cancel=None):
        """Double-precision set operation; retain point/line contacts and holes."""
        if type(other) is not PlanarGeometry or self.frame_id!=other.frame_id:
            raise GeometryError('overlay requires the same planar frame')
        if operation not in ('intersection','union','difference','symmetric_difference'):
            raise GeometryError('unsupported geometry operation')
        limits=_limits(limits);_check_cancel(cancel)
        if self.geometry_id == other.geometry_id:
            if operation in ('intersection','union'):
                _validate_shape(self._geom,limits)
                return self
            return self._from_shape(GeometryCollection(),self.frame_id,limits=limits)
        with _overlay_budget(self._geom,other._geom,limits,budget):
            try:
                out=getattr(shapely,operation)(self._geom,other._geom,grid_size=0.)
            except GEOSException as exc:raise GeometryError('native geometry overlay failed; no repair attempted') from exc
            _check_cancel(cancel)
            return self._from_shape(out,self.frame_id,limits=limits)

    def __reduce__(self): return (_restore_planar,(self._wkb,self.frame_id,self.geometry_id))
    def __deepcopy__(self,memo):memo[id(self)]=self;return self


def _restore_planar(raw, frame_id, expected):
    out=PlanarGeometry.from_wkb(raw,frame_id=frame_id)
    if out.geometry_id!=expected:raise GeometryError('restored planar identity mismatch')
    return out


def geometry_runtime():
    """Versions identify the numerical geometry backend, not a scientific approval."""
    return {'shapely':shapely.__version__,'geos':shapely.geos_version_string,
            'overlay_precision':'binary64, grid_size=0, no repair/snap',
            'spherical_model':'minor great-circle arcs in an explicit open-hemisphere chart'}
