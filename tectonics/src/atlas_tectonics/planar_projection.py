"""W08 sparse conservative views of retained planar material polygons.

An overlap fraction multiplies an extensive donor stock. It never interpolates
thickness or renormalises a cropped view. Exterior values remain attached to the
original donors; a second view is not a second export or a transported state.
Public motion owners perform full source verification around this lower-level
helper. It creates no independent ExecutionContext.
"""
from __future__ import annotations

from array import array
from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
from itertools import chain
import json
import math
import platform
import threading

import numpy as np
import shapely
from shapely.errors import GEOSException
from shapely.strtree import STRtree

from ._validation import TectonicsError, input_shape, read_array
from .geometry import (PlanarGeometry, GeometryError, DEFAULT_GEOMETRY_LIMITS,
                       _label, _json, _check_cancel, _overlay_budget,
                       _validate_shape)
from .resources import select_budget


MAX_PLANAR_POLYGONS = 4096
_ROUND = float(128*np.finfo(float).eps)


def _identity(record, *buffers):
    h = hashlib.sha256(_json(record))
    for buf in buffers:
        h.update(b'\0'); h.update(buf)
    return h.hexdigest()


def _sum(values):
    try:
        result = math.fsum(float(x) for x in values)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError('planar projection account exceeds numerical range') from exc
    if not math.isfinite(result):
        raise TectonicsError('planar projection account exceeds numerical range')
    return result


def _area(a, b, budget, cancel):
    _check_cancel(cancel)
    with _overlay_budget(a, b, DEFAULT_GEOMETRY_LIMITS, budget):
        try:
            overlap = shapely.intersection(a, b)
        except GEOSException as exc:
            raise GeometryError('planar projection intersection failed') from exc
        if not shapely.is_valid(overlap):
            raise GeometryError('invalid planar projection intersection')
        area = float(shapely.area(overlap))
        if not math.isfinite(area) or area < 0:
            raise GeometryError('planar overlap area exceeds numerical range')
        if int(shapely.get_num_coordinates(overlap)) > DEFAULT_GEOMETRY_LIMITS.max_vertices:
            raise GeometryError('planar overlap vertex limit exceeded')
        return area


def _disjoint(shapes, tree, budget, cancel, label):
    candidates = 0
    for i, shape in enumerate(shapes):
        _check_cancel(cancel)
        hits = sorted(int(j) for j in tree.query(shape) if j > i)
        candidates += len(hits)
        if candidates > DEFAULT_GEOMETRY_LIMITS.max_hits:
            raise GeometryError(label+' topology candidate budget exceeded')
        for j in hits:
            if _area(shape, shapes[j], budget, cancel) > 0:
                raise GeometryError(label+' polygons overlap in positive area')


@dataclass(frozen=True, slots=True)
class PlanarProjection:
    """Immutable result; caller accounts for payload lifetime after apply returns."""
    plan_id: str
    projection_id: str
    fields: int
    donors: int
    targets: int
    _inside: bytes = field(repr=False)
    _outside: bytes = field(repr=False)
    _residual: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    @property
    def inside(self):
        return np.frombuffer(self._inside, np.float64).reshape(self.fields, self.targets)

    @property
    def outside(self):
        return np.frombuffer(self._outside, np.float64).reshape(self.fields, self.donors)

    @property
    def residual(self): return np.frombuffer(self._residual, np.float64)

    @property
    def nbytes(self):
        return sum(map(len, (self._inside, self._outside, self._residual, self._record)))

    def descriptor(self): return json.loads(self._record)


class PreparedPlanarProjection:
    """Sparse overlap preparation, retaining its accounting leases until close.

    Each collection contains 1..4096 non-overlapping polygonal geometries in one
    frame, with at most GeometryLimits.max_vertices across both collections.
    STRtree candidates are queried one polygon at a time; no Ns*Nt array exists.
    Native geometry/index allowance is an estimate, not a GEOS heap or RSS cap.
    Shared input definition/native allowances and sparse capacity remain charged
    until close. Caller-owned input arrays and returned result payloads need the
    caller's separate allowance. Join readers before closing the preparation.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared planar projection is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, sources: tuple[PlanarGeometry, ...],
                 targets: tuple[PlanarGeometry, ...], *, source_ids: tuple[str, ...],
                 target_ids: tuple[str, ...], source_id: str, budget=None, cancel=None):
        _check_cancel(cancel); _label(source_id, 'projection source')
        for collection, ids, label in ((sources, source_ids, 'source'),
                                       (targets, target_ids, 'target')):
            if (type(collection) is not tuple or not 1 <= len(collection) <= MAX_PLANAR_POLYGONS
                    or any(type(g) is not PlanarGeometry for g in collection)):
                raise GeometryError('one to 4096 explicit '+label+' planar polygons required')
            if type(ids) is not tuple or len(ids) != len(collection):
                raise GeometryError('one explicit ID per '+label+' polygon required')
            for name in ids: _label(name, label+' polygon ID')
            if len(set(ids)) != len(ids):
                raise GeometryError('duplicate '+label+' polygon ID')
        geometries = sources+targets
        if any(g.frame_id != sources[0].frame_id for g in geometries):
            raise GeometryError('planar projection frame mismatch')
        if any(g.kind not in ('Polygon', 'MultiPolygon') or g.is_empty or
               not math.isfinite(g.area_m2) or g.area_m2 <= 0 for g in geometries):
            raise GeometryError('positive-area polygonal geometry required')
        vertices = sum(g.vertex_count for g in geometries)
        if vertices > DEFAULT_GEOMETRY_LIMITS.max_vertices:
            raise GeometryError('planar projection vertex budget exceeded')
        resource = select_budget(budget); leases = ExitStack()
        try:
            leases.enter_context(resource.reserve(512*vertices+4096*len(geometries)
                +sum(g.retained_bytes for g in geometries)+65536,
                category='planar-projection-geometry'))
            for g in geometries:
                _check_cancel(cancel)
                _validate_shape(g._geom, DEFAULT_GEOMETRY_LIMITS, allow_empty=False)
            source_shapes = tuple(g._geom for g in sources)
            target_shapes = tuple(g._geom for g in targets)
            source_tree, target_tree = STRtree(source_shapes), STRtree(target_shapes)
            _disjoint(source_shapes, source_tree, resource, cancel, 'source')
            _disjoint(target_shapes, target_tree, resource, cancel, 'target')
            donor = array('q'); receiver = array('q'); areas = array('d'); fractions = array('d')
            outside = np.ones(len(sources)); capacity = 0; candidates = 0
            for i, shape in enumerate(source_shapes):
                _check_cancel(cancel)
                hits = sorted(int(j) for j in target_tree.query(shape))
                candidates += len(hits)
                if candidates > DEFAULT_GEOMETRY_LIMITS.max_hits:
                    raise GeometryError('planar projection candidate budget exceeded')
                first = len(fractions)
                for j in hits:
                    area = _area(shape, target_shapes[j], resource, cancel)
                    if not area: continue  # Boundary contact transports no area.
                    fraction = area/sources[i].area_m2
                    if not math.isfinite(fraction) or fraction <= 0:
                        raise GeometryError('positive planar overlap fraction is unresolvable')
                    if len(donor) == capacity:
                        count = min(256, DEFAULT_GEOMETRY_LIMITS.max_hits-capacity)
                        leases.enter_context(resource.reserve(128*count,
                            category='planar-projection-sparse'))
                        capacity += count
                    donor.append(i); receiver.append(j); areas.append(area); fractions.append(fraction)
                total = _sum(fractions[first:])
                # Only signed roundoff in the complementary fraction may become
                # zero. Positive intersection fractions are never rescaled.
                if total > 1+_ROUND:
                    raise GeometryError('planar overlaps exceed donor area')
                outside[i] = max(0., 1-total)
            order = np.argsort(np.asarray(receiver, np.int64), kind='stable')
            ordered_targets = np.asarray(receiver, np.int64)[order]
            starts = (np.r_[0, np.flatnonzero(np.diff(ordered_targets))+1]
                      if len(order) else np.empty(0, np.int64))
            runtime = dict(python=platform.python_version(), numpy=np.__version__,
                           shapely=shapely.__version__, geos=shapely.geos_version_string)
            record = dict(method='atlas.w08-planar-projection.v1', source=source_id,
                frame=sources[0].frame_id, source_polygons=list(zip(source_ids,
                    (g.geometry_id for g in sources))), target_polygons=list(zip(target_ids,
                    (g.geometry_id for g in targets))), runtime=runtime,
                exterior='retained-per-donor-outside-view-not-deleted-or-re-exported')
            self.sources = sources; self.targets = targets
            self.source_ids = source_ids; self.target_ids = target_ids; self.source_id = source_id
            self._donor = np.asarray(donor, np.int64).tobytes()
            self._target = np.asarray(receiver, np.int64).tobytes()
            self._area = np.asarray(areas, np.float64).tobytes()
            self._fraction = np.asarray(fractions, np.float64).tobytes()
            self._outside = outside.tobytes()
            self._order = order.astype(np.int64).tobytes()
            self._starts = starts.astype(np.int64).tobytes()
            self._record = _json(record)
            self.plan_id = _identity(record, self._donor, self._target, self._area,
                                     self._fraction, self._outside)
            self.candidate_count = candidates
            self._trees = (source_tree, target_tree)
            self._budget = resource; self._leases = leases
            self._closed = False; self._active = 0; self._lock = threading.Lock()
            _check_cancel(cancel); self._sealed = True
        except BaseException:
            leases.close(); raise

    @property
    def donor(self): return np.frombuffer(self._donor, np.int64)
    @property
    def target(self): return np.frombuffer(self._target, np.int64)
    @property
    def area_m2(self): return np.frombuffer(self._area, np.float64)
    @property
    def fraction(self): return np.frombuffer(self._fraction, np.float64)
    @property
    def outside_fraction(self): return np.frombuffer(self._outside, np.float64)
    @property
    def nbytes(self):
        return sum(map(len, (self._donor, self._target, self._area, self._fraction,
            self._outside, self._order, self._starts, self._record)))

    def descriptor(self):
        return dict(json.loads(self._record), plan_id=self.plan_id,
                    candidate_count=self.candidate_count, positive_pairs=len(self.donor))

    def apply(self, extensive, *, cancel=None):
        with self._lock:
            if self._closed: raise GeometryError('planar projection is closed')
            object.__setattr__(self, '_active', self._active+1)
        try:
            _check_cancel(cancel)
            shape = input_shape(extensive, 'extensive donor stocks')
            ns, nt = len(self.sources), len(self.targets)
            if len(shape) != 2 or shape[0] < 1 or shape[1] != ns:
                raise TectonicsError('extensive stocks require (fields, donors) shape')
            fields = shape[0]; pairs = len(self.donor)
            with self._budget.reserve(48*fields*(ns+nt)+64*pairs+8192,
                                      category='planar-projection-apply'):
                stock = read_array(extensive, 'extensive donor stocks')
                inside = np.zeros((fields, nt)); residual = np.empty(fields)
                with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                    outside = stock*self.outside_fraction
                order = np.frombuffer(self._order, np.int64)
                starts = np.frombuffer(self._starts, np.int64)
                ends = np.r_[starts[1:], pairs]
                donor, target = self.donor, self.target
                for k in range(fields):
                    _check_cancel(cancel)
                    with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                        values = stock[k, donor]*self.fraction
                    if (not np.isfinite(values).all() or not np.isfinite(outside[k]).all()
                            or np.any((stock[k, donor] != 0) & (values == 0))
                            or np.any((stock[k] != 0) & (self.outside_fraction > 0)
                                      & (outside[k] == 0))):
                        raise TectonicsError('planar projected stock exceeds numerical range')
                    values = values[order]
                    for start, end in zip(starts, ends):
                        _check_cancel(cancel)
                        inside[k, target[order[start]]] = _sum(values[start:end])
                    residual[k] = _sum(chain(inside[k], outside[k], -stock[k]))
                    scale = _sum(chain(np.abs(stock[k]), np.abs(inside[k]), np.abs(outside[k])))
                    if abs(residual[k]) > _ROUND*scale:
                        raise TectonicsError('planar extensive account does not reconcile')
                record = dict(operation='atlas.w08-planar-projection-result.v1', plan=self.plan_id,
                    source_ids=self.source_ids, target_ids=self.target_ids,
                    fields=fields, account_residuals=residual.tolist(),
                    exterior='retained-per-donor-outside-view-not-deleted-or-re-exported')
                payload = inside.tobytes(), outside.tobytes(), residual.tobytes(), _json(record)
                result = PlanarProjection(self.plan_id, _identity(record, stock.tobytes(), *payload),
                                          fields, ns, nt, *payload)
                _check_cancel(cancel)
                return result
        finally:
            with self._lock:
                object.__setattr__(self, '_active', self._active-1)

    def close(self):
        with self._lock:
            if self._active: raise GeometryError('join active projections before closing')
            if not self._closed:
                object.__setattr__(self, '_trees', ())
                object.__setattr__(self, '_closed', True)
                self._leases.close()

    def __enter__(self):
        if self._closed: raise GeometryError('planar projection is closed')
        return self

    def __exit__(self, *args): self.close()
