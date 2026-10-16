"""W08 material origin/destination accounts across two identified region states.

Each initial material piece is intersected with final regions pulled back into
its donor's material coordinates, or assigned to the retained exterior. This
records endpoint material transfer, not the
number of crossings along an unresolved intermediate trajectory. The calling
material owner verifies complete source identity; no ExecutionContext is created.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from itertools import chain
import json
import math

import numpy as np
import shapely
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon

from ._validation import TectonicsError, input_shape, read_array
from .geometry import (PlanarGeometry, GeometryError, DEFAULT_GEOMETRY_LIMITS,
                       _label, _json, _check_cancel, _overlay_budget, _validate_shape)
from .planar_projection import PreparedPlanarProjection, _identity, _sum
from .resources import WorkBudget, DEFAULT_BUDGET, select_budget


MAX_REGIONS = 64
MAX_PIECES = 4096
MAP_ERROR = 1e-10
_ROUND = float(128*np.finfo(float).eps)
_DEFAULT_BUDGET = WorkBudget(128*1024**2, parent=DEFAULT_BUDGET)


def _names(values, count, name):
    if type(values) is not tuple or len(values) != count:
        raise TectonicsError('one explicit '+name+' per geometry required')
    for value in values: _label(value, name)
    if len(set(values)) != count: raise TectonicsError('duplicate '+name)


def _area_shape(shape):
    """Keep occupied polygons from an overlay; zero-area contacts carry no stock."""
    if shape.is_empty or shape.area == 0: return None
    if shape.geom_type in ('Polygon', 'MultiPolygon'): return shape
    polygons = []
    def visit(part):
        if part.geom_type == 'Polygon': polygons.append(part)
        elif hasattr(part, 'geoms'):
            for child in part.geoms: visit(child)
    visit(shape)
    if not polygons: raise GeometryError('positive overlap lacks occupied polygon area')
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def _overlay(a, b, operation, budget, cancel):
    _check_cancel(cancel)
    with _overlay_budget(a, b, DEFAULT_GEOMETRY_LIMITS, budget):
        try: result = getattr(shapely, operation)(a, b)
        except GEOSException as exc:
            raise GeometryError('exchange '+operation+' failed') from exc
        _validate_shape(result, DEFAULT_GEOMETRY_LIMITS)
        return result


def _map(shape, deformation, old_origin, new_origin, frame, budget, cancel):
    _check_cancel(cancel)
    count = int(shapely.get_num_coordinates(shape))
    with budget.reserve(1024*count+16384, category='planar-exchange-map'):
        xy = shapely.get_coordinates(shape)
        with np.errstate(over='ignore', invalid='ignore', under='ignore'):
            local = (xy-old_origin)@deformation.T
            mapped = new_origin+local
        scale = max(float(np.max(np.ptp(local, axis=0))), math.sqrt(float(shape.area)))
        if (not np.isfinite(mapped).all() or
                np.max(np.abs((mapped-new_origin)-local)) > MAP_ERROR*scale):
            raise GeometryError('exchange motion is unresolvable in this coordinate frame')
        try: result = shapely.set_coordinates(shape, mapped)
        except GEOSException as exc: raise GeometryError('exchange map failed') from exc
        _validate_shape(result, DEFAULT_GEOMETRY_LIMITS, allow_empty=False)
        expected = float(np.linalg.det(deformation))*float(shape.area)
        if not math.isfinite(expected) or expected <= 0 or abs(result.area-expected) > MAP_ERROR*expected:
            raise GeometryError('exchange mapped area disagrees with deformation')
        return PlanarGeometry._from_shape(result, frame)


def _balance(values, scale, message):
    residual = _sum(values)
    if abs(residual) > _ROUND*scale: raise TectonicsError(message)
    return residual


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    exchange_id: str
    fields: int
    destinations: int
    _transfer: bytes = field(repr=False)
    _initial: bytes = field(repr=False)
    _final: bytes = field(repr=False)
    _residual: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    @property
    def transfer(self):
        return np.frombuffer(self._transfer, np.float64).reshape(
            self.fields, self.destinations, self.destinations)
    @property
    def initial_stock(self):
        return np.frombuffer(self._initial, np.float64).reshape(self.fields, self.destinations)
    @property
    def final_stock(self):
        return np.frombuffer(self._final, np.float64).reshape(self.fields, self.destinations)
    @property
    def residual(self): return np.frombuffer(self._residual, np.float64)
    @property
    def nbytes(self):
        return sum(map(len, (self._transfer, self._initial, self._final,
                             self._residual, self._record)))
    def descriptor(self): return json.loads(self._record)


def planar_exchange(start_polygons, end_polygons, deformation_between, extensive, *,
                    start_regions, end_regions, parcel_ids, region_ids, exterior_id,
                    source_id, budget=None, cancel=None):
    """Return signed extensive transfer[field, origin, destination].

    The final index names retained exterior on both axes. Material parcels are
    simple polygons with corresponding ordered boundary vertices at both ends.
    Every positive, conditioned 2x2 map is checked against its complete endpoint.
    Initial-region intersections and exact set-difference exterior pieces stay
    in their donor's material coordinates. Candidate final regions are mapped
    back about the corresponding first exterior vertices. Independent donor maps
    never manufacture a new global mesh from separately rounded shared edges.
    All geometry/work allowances are released on return or failure. The caller
    separately accounts for retained input geometry and result payload lifetime;
    admission estimates do not enforce GEOS heap or process RSS limits.
    """
    _check_cancel(cancel); _label(source_id, 'exchange source'); _label(exterior_id, 'exterior ID')
    if (type(start_polygons) is not tuple or not 1 <= len(start_polygons) <= MAX_PIECES
            or type(end_polygons) is not tuple or len(end_polygons) != len(start_polygons)):
        raise GeometryError('one to 4096 corresponding start/end material polygons required')
    n = len(start_polygons)
    if (type(start_regions) is not tuple or not 1 <= len(start_regions) <= MAX_REGIONS
            or type(end_regions) is not tuple or len(end_regions) != len(start_regions)):
        raise GeometryError('one to 64 corresponding start/end regions required')
    r = len(start_regions); size = r+1
    _names(parcel_ids, n, 'parcel ID'); _names(region_ids, r, 'region ID')
    if exterior_id in region_ids: raise TectonicsError('exterior must have a distinct explicit ID')
    all_geometry = start_polygons+end_polygons+start_regions+end_regions
    if any(type(g) is not PlanarGeometry for g in all_geometry):
        raise GeometryError('explicit planar geometry required')
    frame = start_polygons[0].frame_id
    if any(g.frame_id != frame for g in all_geometry): raise GeometryError('exchange frame mismatch')
    if any(g.kind != 'Polygon' or g.is_empty or g.area_m2 <= 0 for g in start_polygons+end_polygons):
        raise GeometryError('simple positive-area material polygons required')
    vertices = sum(g.vertex_count for g in all_geometry)
    if vertices > DEFAULT_GEOMETRY_LIMITS.max_vertices:
        raise GeometryError('exchange input vertex budget exceeded')
    if input_shape(deformation_between) != (n, 2, 2):
        raise TectonicsError('one full 2x2 deformation matrix per material polygon required')
    shape = input_shape(extensive)
    if len(shape) != 2 or shape[0] < 1 or shape[1] != n:
        raise TectonicsError('extensive stocks require (fields, parcels) shape')
    fields = shape[0]; resource = _DEFAULT_BUDGET if budget is None else select_budget(budget)
    with ExitStack() as leases:
        leases.enter_context(resource.reserve(48*fields*(n+size*size)+512*vertices
            +4096*len(all_geometry)+65536, category='planar-exchange-work'))
        deformation = read_array(deformation_between, 'exchange deformation')
        stock = read_array(extensive, 'exchange extensive stocks')
        origins = []; endpoints = []
        for i, (start, end) in enumerate(zip(start_polygons, end_polygons)):
            _check_cancel(cancel)
            f = deformation[i]
            j = float(np.linalg.det(f))
            if not math.isfinite(j) or j <= 0 or np.linalg.cond(f)*np.finfo(float).eps > MAP_ERROR:
                raise GeometryError('inverted, singular or unresolved exchange deformation')
            before, after = shapely.get_coordinates(start._geom), shapely.get_coordinates(end._geom)
            if before.shape != after.shape:
                raise GeometryError('corresponding ordered material vertices required')
            origin = np.asarray(start._geom.exterior.coords[0]); endpoint = np.asarray(end._geom.exterior.coords[0])
            mapped = _map(start._geom, f, origin, endpoint, frame, resource, cancel)
            scale = max(math.sqrt(end.area_m2), float(np.max(np.ptp(after, axis=0))))
            if np.max(np.abs(shapely.get_coordinates(mapped._geom)-after)) > MAP_ERROR*scale:
                raise GeometryError('deformation disagrees with corresponding endpoint vertices')
            symmetric = _overlay(mapped._geom, end._geom, 'symmetric_difference', resource, cancel)
            if (abs(mapped.area_m2-end.area_m2) > MAP_ERROR*end.area_m2
                    or symmetric.area > MAP_ERROR*end.area_m2):
                raise GeometryError('deformation disagrees with complete endpoint polygon')
            origins.append(origin); endpoints.append(endpoint)
        pieces = []; donors = []; origin_regions = []; piece_fraction = []; generated_vertices = 0
        def append_piece(shape, donor, region):
            nonlocal generated_vertices
            shape = _area_shape(shape)
            if shape is None: return
            if len(pieces) == MAX_PIECES: raise GeometryError('exchange generated-piece limit exceeded')
            count = int(shapely.get_num_coordinates(shape))
            generated_vertices += count
            if generated_vertices+sum(g.vertex_count for g in end_regions) > DEFAULT_GEOMETRY_LIMITS.max_vertices:
                raise GeometryError('exchange generated-piece vertex budget exceeded')
            leases.enter_context(resource.reserve(1024*count+8192,
                category='planar-exchange-pieces'))
            piece = PlanarGeometry._from_shape(shape, frame)
            fraction = float(shape.area)/start_polygons[donor].area_m2
            if not math.isfinite(fraction) or fraction <= 0:
                raise GeometryError('initial material-piece fraction is unresolvable')
            pieces.append(piece); donors.append(donor); origin_regions.append(region); piece_fraction.append(fraction)
        with PreparedPlanarProjection(start_polygons, start_regions, source_ids=parcel_ids,
                target_ids=region_ids, source_id=source_id, budget=resource, cancel=cancel) as initial_plan:
            initial_view = initial_plan.apply(stock, cancel=cancel)
            initial_stock = np.column_stack((initial_view.inside,
                [_sum(row) for row in initial_view.outside]))
            initial_plan_id = initial_plan.plan_id
            offset = 0
            for i, start in enumerate(start_polygons):
                exterior = start._geom; fractions_start = len(piece_fraction)
                while offset < len(initial_plan.donor) and initial_plan.donor[offset] == i:
                    region = int(initial_plan.target[offset]); area = start_regions[region]._geom
                    append_piece(_overlay(start._geom, area, 'intersection', resource, cancel), i, region)
                    exterior = _overlay(exterior, area, 'difference', resource, cancel)
                    offset += 1
                append_piece(exterior, i, r)
                _balance(chain(piece_fraction[fractions_start:], (-1.,)), 2.,
                         'initial material pieces do not reconcile')
        with PreparedPlanarProjection(end_polygons, end_regions, source_ids=parcel_ids,
                target_ids=region_ids, source_id=source_id, budget=resource, cancel=cancel) as final_plan:
            final_view = final_plan.apply(stock, cancel=cancel)
            final_stock = np.column_stack((final_view.inside,
                [_sum(row) for row in final_view.outside]))
            final_plan_id = final_plan.plan_id
            final_donor = final_plan.donor.copy(); final_target = final_plan.target.copy()
            final_fraction = final_plan.fraction.copy(); final_outside = final_plan.outside_fraction.copy()
        sparse_piece = []; destinations = []; fractions = []; capacity = 0
        piece_projections = []; piece_offset = 0; final_offset = 0
        donor_fraction_residuals = []
        def transfer_piece(piece_index, destination, fraction):
            nonlocal capacity
            if fraction <= 0: return
            if len(fractions) == capacity:
                count = min(256, DEFAULT_GEOMETRY_LIMITS.max_hits-capacity)
                if count <= 0: raise GeometryError('exchange transfer candidate budget exceeded')
                leases.enter_context(resource.reserve(384*count, category='planar-exchange-transfers'))
                capacity += count
            sparse_piece.append(piece_index); destinations.append(destination)
            fractions.append(fraction*piece_fraction[piece_index])
        for i, end in enumerate(end_polygons):
            _check_cancel(cancel)
            first_piece = piece_offset
            while piece_offset < len(pieces) and donors[piece_offset] == i: piece_offset += 1
            first_final = final_offset
            while final_offset < len(final_donor) and final_donor[final_offset] == i: final_offset += 1
            targets = final_target[first_final:final_offset]
            first_transfer = len(fractions)
            if not len(targets):
                # The exact declared endpoint is disjoint from every region.
                for k in range(first_piece, piece_offset): transfer_piece(k, r, 1.)
                piece_projections.append(dict(parcel=i, exact_endpoint='exterior'))
            elif len(targets) == 1 and shapely.covers(end_regions[int(targets[0])]._geom, end._geom):
                # A fully contained donor needs no reconstructed endpoint mesh.
                destination = int(targets[0])
                for k in range(first_piece, piece_offset): transfer_piece(k, destination, 1.)
                piece_projections.append(dict(parcel=i, exact_endpoint=destination))
            else:
                inverse = np.linalg.inv(deformation[i])
                with resource.reserve(1024*sum(end_regions[int(j)].vertex_count for j in targets)
                        +8192*len(targets), category='planar-exchange-pullback'):
                    pulled = tuple(_map(end_regions[int(j)]._geom, inverse, endpoints[i], origins[i],
                        frame, resource, cancel) for j in targets)
                    ids = tuple('exchange-piece-'+str(k) for k in range(first_piece, piece_offset))
                    with PreparedPlanarProjection(tuple(pieces[first_piece:piece_offset]), pulled,
                            source_ids=ids, target_ids=tuple(region_ids[int(j)] for j in targets),
                            source_id=source_id, budget=resource, cancel=cancel) as piece_plan:
                        for k, j, fraction in zip(piece_plan.donor, piece_plan.target, piece_plan.fraction):
                            transfer_piece(first_piece+int(k), int(targets[int(j)]), float(fraction))
                        for k, fraction in enumerate(piece_plan.outside_fraction):
                            transfer_piece(first_piece+k, r, float(fraction))
                        piece_projections.append(dict(parcel=i, material_projection=piece_plan.plan_id))
            # Donor-local clipping preserves its exact original support. Compare
            # every destination with its independently measured declared endpoint,
            # including zero-stock donors that global signed accounts could hide.
            expected = np.zeros(size); actual = [[] for _ in range(size)]
            expected[targets] = final_fraction[first_final:final_offset]
            expected[r] = final_outside[i]
            for j, fraction in zip(destinations[first_transfer:], fractions[first_transfer:]):
                actual[j].append(fraction)
            residuals = [_balance(chain(actual[j], (-expected[j],)), 2.,
                'donor material transfer disagrees with independent endpoint fractions') for j in range(size)]
            _balance(chain(fractions[first_transfer:], (-1.,)), 2.,
                     'donor material transfer fractions do not reconcile')
            donor_fraction_residuals.append(max(map(abs, residuals)))
        with resource.reserve(48*fields*len(pieces), category='planar-exchange-aggregation'):
            donors = np.asarray(donors, np.int64); origin_regions = np.asarray(origin_regions, np.int64)
            sparse_piece = np.asarray(sparse_piece, np.int64); destinations = np.asarray(destinations, np.int64)
            fractions = np.asarray(fractions)
            if np.any(fractions <= 0): raise TectonicsError('exchange transfer fraction underflows')
            keys = origin_regions[sparse_piece]*size+destinations
            order = np.argsort(keys, kind='stable'); keys = keys[order]
            parcel = donors[sparse_piece[order]]; fractions = fractions[order]
            starts = np.r_[0, np.flatnonzero(np.diff(keys))+1]
            ends = np.r_[starts[1:], len(keys)]
            transfer = np.zeros((fields, size*size)); residual = np.empty(fields)
            row_residuals = np.empty((fields, size)); column_residuals = np.empty((fields, size))
            for k in range(fields):
                _check_cancel(cancel)
                with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                    values = stock[k, parcel]*fractions
                if not np.isfinite(values).all() or np.any((stock[k, parcel] != 0) & (values == 0)):
                    raise TectonicsError('exchange transfer stock exceeds numerical range')
                for begin, end in zip(starts, ends): transfer[k, keys[begin]] = _sum(values[begin:end])
                scale = _sum(chain(np.abs(stock[k]), np.abs(values),
                                   np.abs(initial_stock[k]), np.abs(final_stock[k])))
                matrix = transfer[k].reshape(size, size)
                for j in range(size):
                    row_residuals[k, j] = _balance(chain(matrix[j], (-initial_stock[k, j],)), scale,
                        'exchange row does not reconcile with independent initial projection')
                    column_residuals[k, j] = _balance(chain(matrix[:, j], (-final_stock[k, j],)), scale,
                        'exchange column does not reconcile with independent final projection')
                _balance(chain(transfer[k], -stock[k]), scale, 'exchange transfer account does not reconcile')
                residual[k] = _balance(chain(final_stock[k], -initial_stock[k]), scale,
                    'exchange endpoint stocks do not reconcile')
            record = dict(operation='atlas.w08-planar-exchange.v2', source=source_id,
                frame=frame, parcel_ids=parcel_ids, region_ids=region_ids, exterior_id=exterior_id,
                account_order=(*region_ids, exterior_id), initial_projection=initial_plan_id,
                final_projection=final_plan_id, piece_projection=_identity(piece_projections),
                transport='donor-material-coordinates-with-exact-endpoint-containment',
                donor_fraction_max_residuals=donor_fraction_residuals,
                generated_pieces=len(pieces), account_residuals=residual.tolist(),
                row_residuals=row_residuals.tolist(), column_residuals=column_residuals.tolist(),
                meaning='endpoint-material-origin-to-destination-not-intermediate-crossing-count',
                exterior='retained-exterior-material-with-explicit-return')
            payload = transfer.tobytes(), initial_stock.tobytes(), final_stock.tobytes(), residual.tobytes(), _json(record)
            result = ExchangeResult(_identity(record, deformation.tobytes(), stock.tobytes(), *payload),
                                    fields, size, *payload)
        _check_cancel(cancel)
        return result
