"""Thermal metrics on the actual differential ALE component partition.

The same issued convex components identify material and heat cells. Planar
thermal facets approximate curved physical support with a declared volume-error
bound; they never supply the physical material volume or erase a sliver.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from bisect import bisect_right
from itertools import product
from io import BytesIO
import json
import weakref

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_volume_overlap as O
from . import integration_wall_measures as W
from . import integration_exterior_mesh as E
from . import integration_differential_geometry as D
from .integration_collar_geometry import FullCellFunding
from .integration_spatial_ale import SpatialALEBounds
from .integration_regional_inventory import _width
from .integration_poly_tiles import clipped_tiles
from .resources import WorkBudget


def _reservoir_thermal_boundaries(faces, cells, native_boxes, basal, budget, arena):
    """Require declared heat conditions on every surface of the carved union.

    The finite compartments are not spatial heat cells. Their complete exposed
    surface, not only the native basal face, is therefore an external thermal
    boundary. Exact rectangles are shared with the physical pressure closure.
    """
    if not basal:
        return []
    from .integration_differential_pressure import _cut_faces
    first = native_boxes[0]
    if any(c.origin_m != first.origin_m or c.basis != first.basis for c in native_boxes):
        raise V.VolumeError('native cells do not share the actual reservoir chart')
    lo = tuple(min(c.lower_m[j] for c in native_boxes) for j in range(3))
    hi = tuple(max(c.upper_m[j] for c in native_boxes) for j in range(3))
    native = V.CartesianCell(lo, hi, first.origin_m, first.basis, budget=budget)
    if sum((c.volume_m3 for c in native_boxes), Q(0)) != native.volume_m3:
        raise V.VolumeError('complete native grid does not cover its bounding box')
    boxes = tuple(V.CartesianCell.from_record(r, budget=budget)
                  for r in basal['excluded_cells'])
    cuts = tuple(_cut_faces(boxes, native, budget))
    required = []
    for face in faces:
        if len(face['owners']) != 1:
            continue
        points = tuple(tuple(map(W._decode, p)) for p in face['vertices_m'])
        matches = []
        for cell, axis, end in cuts:
            local = tuple(tuple(sum(cell.basis[i][j]*(p[i]-cell.origin_m[i]) for i in range(3))
                                for j in range(3)) for p in points)
            at = (cell.lower_m, cell.upper_m)[end][axis]
            if not all(p[axis] == at for p in local):
                continue
            tangents = tuple(j for j in range(3) if j != axis)
            polygon = tuple((p[tangents[0]], p[tangents[1]]) for p in local)
            if E._area(polygon) < 0:
                polygon = tuple(reversed(polygon))
            u, v = tangents
            rectangle = ((cell.lower_m[u], cell.lower_m[v]), (cell.upper_m[u], cell.lower_m[v]),
                         (cell.upper_m[u], cell.upper_m[v]), (cell.lower_m[u], cell.upper_m[v]))
            overlap = E._intersection(polygon, rectangle, arena)
            if overlap:
                if E._area(overlap) != E._area(polygon):
                    raise V.VolumeError('thermal face straddles a reservoir cut; refine its conforming partition')
                matches.append(dict(cell_id=cell.cell_id, axis=axis, end=end))
        if matches:
            if cells[face['owners'][0]]['kind'] != 'exterior' or len(matches) != 1:
                raise V.VolumeError('reservoir cut has ambiguous thermal ownership')
            face.update(boundary_role='finite-basal-reservoir-exterior-cut',
                        reservoir_cut=matches[0])
            required.append(face['face_id'])
    return required


def _thermal_boxes(voxel, subdivisions, budget, *, shared_lines=None, poly=None):
    """A shared dyadic lattice, identical on either side of a voxel face."""
    if subdivisions == 1 and shared_lines is None:
        yield voxel
        return
    lines = (tuple(tuple(a+(b-a)*Q(i, subdivisions) for i in range(subdivisions+1))
                   for a, b in zip(voxel.lower_m, voxel.upper_m)) if shared_lines is None else
             tuple(tuple(q for q in shared_lines[j] if voxel.lower_m[j] <= q <= voxel.upper_m[j])
                   for j in range(3)))
    ranges = tuple(range(len(axis)-1) for axis in lines)
    if poly:
        vertices = B._points(poly)
        local = tuple(tuple(sum(voxel.basis[i][j]*(p[i]-voxel.origin_m[i]) for i in range(3))
                            for j in range(3)) for p in vertices)
        ranges = tuple(tuple(i for i in ranges[j] if lines[j][i] < max(p[j] for p in local)
                            and lines[j][i+1] > min(p[j] for p in local)) for j in range(3))
    for at in product(*ranges):
        yield V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)),
            tuple(lines[j][at[j]+1] for j in range(3)), voxel.origin_m, voxel.basis, budget=budget)


def _aggregate_cells(cells, faces, groups, boxes, arena):
    """Cancel only internal facets and sum exact moments, never physical stocks.

    The result is admitted only with a centre in its strict star-shaped kernel.
    HMM needs that kernel and the full first-moment identity, not convexity of
    each original radial approximation. No face, capacity or material is lost.
    """
    by_piece = {c['cell_id']: c for c in cells}
    signs = {c['cell_id']: dict(c['faces']) for c in cells}
    arena.keep((), 4*len(cells)+3*len(faces)+sum(len(c['faces']) for c in cells))
    grouped = {}
    for key, cell in by_piece.items():
        grouped.setdefault(groups.get(key, key), []).append(cell)
    merged = {}
    for key, pieces in grouped.items():
        volume = sum((W._decode(c['volume_m3']) for c in pieces), Q(0))
        centre = tuple(sum((W._decode(c['volume_m3'])*W._decode(c['centroid_m'][j])
                           for c in pieces), Q(0))/volume for j in range(3))
        merged[key] = dict(pieces[0], cell_id=key, volume_m3=E._enc(volume),
                           centroid_m=E._point(centre), faces=[])
    kept = []
    for face in faces:
        owners = [groups.get(k, k) for k in face['owners']]
        if len(owners) == 2 and owners[0] == owners[1]:
            continue
        emitted = dict(face, owners=owners)
        kept.append(emitted)
        for old, new in zip(face['owners'], owners):
            sign = signs[old][face['face_id']]
            merged[new]['faces'].append([face['face_id'], sign])
    by_face = {f['face_id']: f for f in kept}
    for key, cell in merged.items():
        centre = tuple(map(W._decode, cell['centroid_m']))
        about, scale = E._cleared(centre)
        rows = [E._signed_face(by_face[fid], sign, about, scale) for fid, sign in cell['faces']]
        # normal.centre >= normal.centroid is area.(centroid-centre) <= 0. The
        # rational planes are built only for a cell that needs a kernel point,
        # with the same values in the same order for the same clips.
        if any(nonpositive for nonpositive, _ in rows):
            planes = []
            for fid, sign in cell['faces']:
                face = by_face[fid]
                normal = tuple(sign*W._decode(q) for q in face['area_vector_m2'])
                point = tuple(map(W._decode, face['centroid_m']))
                planes.append((*normal, O._dot(normal, point)))
            kernel = B._box(boxes[key])
            for plane in planes:
                kernel = B._clip(kernel, plane, arena)
                if not kernel:
                    break
            volume, candidate = E._cell_metrics(kernel, arena)
            if volume <= 0 or any(O._dot(p[:3], candidate) >= p[3] for p in planes):
                raise V.VolumeError('aggregated thermal cell has no strict star-shaped kernel; refine physical partition')
            centre = candidate
            cell['volume_centroid_m'] = cell['centroid_m']
            cell['centroid_m'] = E._point(centre)
            cell['metric_point_kind'] = 'strict kernel point; not the volume centroid'
        # The closure and first-moment identity holds about every point or
        # none (E._closure_fails), so it is the same about a kernel point.
        volume = W._decode(cell['volume_m3'])
        if E._admitted_closure_fails([term for _, term in rows], volume, arena.resource):
            raise V.VolumeError('aggregated thermal metric closure or first-moment identity failed')
        cell['faces'].sort()
    return [merged[k] for k in sorted(merged)], kept


def _compact_witness(box, encoded, component, posed, layer):
    """Short dyadic chart coordinates, proved strictly inside true support.

    The original exact witness can have large coprime denominators. Introducing
    those into every subsequent mesh intersection needlessly grows rationals.
    A derived open-neighbourhood bound, NOT an accuracy tolerance, permits a
    shorter point. Its membership is rechecked with exact inequalities.
    """
    point = tuple(map(W._decode, encoded))
    local = tuple(sum(box.basis[i][j]*(point[i]-box.origin_m[i]) for i in range(3))
                  for j in range(3))
    margin = min(*(x-a for x, a in zip(local, box.lower_m)),
                 *(b-x for x, b in zip(local, box.upper_m)))
    square = O._dot(point, point)
    radial = min(square-layer.bottom_radius_m**2, layer.top_radius_m**2-square)
    lipschitz = max(sum(map(abs, row)) for row in box.basis)
    delta = min(Q(1), margin/2, radial/(2*(2*lipschitz*sum(map(abs, point))+3*lipschitz**2)))
    constraints = []
    for name, sign in component['constraints']:
        item = posed['constraints'][name]
        normal = tuple(sign*W._decode(v) for v in item['normal'])
        offset, error = sign*W._decode(item['offset']), W._decode(item['error_euclidean'])
        slack = O._dot(normal, point)-offset-error*sum(map(abs, point))
        rate = lipschitz*(sum(map(abs, normal))+3*error)
        if rate:
            delta = min(delta, slack/(2*rate))
        elif slack <= 0:
            raise V.VolumeError('certified witness has no strict physical constraint neighbourhood')
        constraints.append((normal, offset, error))
    if delta <= 0:
        raise V.VolumeError('certified witness has no strict physical neighbourhood')
    span = max(b-a for a, b in zip(box.lower_m, box.upper_m))
    scale = 1
    while span >= 2*delta*scale:
        scale *= 2
    result = []
    for x, a, b in zip(local, box.lower_m, box.upper_m):
        t = (x-a)*scale/(b-a)
        nearest = (2*t.numerator+t.denominator)//(2*t.denominator)
        result.append(a+(b-a)*Q(nearest, scale))
    result = tuple(result)
    physical = tuple(box.origin_m[i]+sum(box.basis[i][j]*result[j] for j in range(3)) for i in range(3))
    if (not all(a < x < b for x, a, b in zip(result, box.lower_m, box.upper_m)) or
            not layer.bottom_radius_m**2 < O._dot(physical, physical) < layer.top_radius_m**2 or
            any(O._dot(n, physical)-d <= e*sum(map(abs, physical)) for n, d, e in constraints)):
        raise V.VolumeError('compact thermal witness failed exact true-support membership')
    return result


def _unbooked(booked, logical):
    """True when the exact closure carries no material in this component.

    The heat solve requires the mesh cells to be exactly the components with a
    positive BOOKED end volume. With the closure in hand that inventory, and
    no size threshold, decides which components receive a cell: a component
    with no booked material needs none, whether its certified volume is zero,
    undecided (two cones that only touch keep ``[0, tiny]`` at every pose
    precision) or positive. The difference between its true and its booked
    volume is already the closure's own signed geometry-error account, not a
    thermal surrogate error. Booked material without a certified positive
    subset still refuses. Without a closure nothing is decided here.
    """
    return booked is not None and not booked.get(logical, Q(0))


def _unposed(booked, row):
    """True when the exact closure books no material in any component of a support.

    Both passes over the supports leave every unbooked component before they
    read a pose, so the poses of such a support are never used and are not
    computed after their retained input fields have been validated. The support
    is still read, its voxel and radial layer are still rebuilt, and each of
    its components is still counted as unbooked. Unproven constraint shapes use
    the original pose path. Without a closure every support is posed.
    """
    return booked is not None and all(_unbooked(booked, c['logical_cell_id']) for c in row['components'])


def _support_cells(support, *, endpoint, integration_width, max_leaves, budget, arena,
                   subdivisions=1, shared_lines=None, measures=None, missing=None,
                   retain_polys=True, booked=None, unbooked=None):
    """One convex thermal cell per actual physical component, or exact zero.

    This private geometry seam does not establish complete source coverage. The
    public builder below requires the complete issued ALE component inventory.
    """
    if type(support) is not D.DifferentialSupport or support._resource is not budget:
        raise V.VolumeError('issued physical components on the same budget required')
    # Without a closure the statements keep their order. With one the support
    # is read first, because its components decide whether it is posed.
    posed = None if booked is not None else D.posed_support(support, endpoint=endpoint, budget=budget).record()
    row = support.record()
    if booked is not None:
        if _unposed(booked, row):
            D._validate_unposed_support(support, row, endpoint=endpoint, budget=budget)
        else:
            posed = D._mesh_posed_support(support, row, endpoint=endpoint, booked=booked, budget=budget).record()
    voxel = V.CartesianCell.from_record(row['voxel'], budget=budget)
    layer = V.RadialLayer(*(W._decode(row['radial_layer'][k]) for k in
                            ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    planes = {} if posed is None else {k: (tuple(map(W._decode, r['normal'])), W._decode(r['offset']))
                                       for k, r in posed['constraints'].items()}
    result = []
    for component in row['components']:
        logical = component['logical_cell_id']
        if _unbooked(booked, logical):
            if unbooked is not None:
                unbooked.append(logical)
            continue
        cache_key = (support.support_id, logical, endpoint)
        measure = None if measures is None else measures.get(cache_key)
        if measure is None:
            measure = D.component_volume_bounds(support, logical, endpoint=endpoint,
                max_width_m3=integration_width, max_leaves=max_leaves,
                positive_witness=True, budget=budget).record()
            if measures is not None:
                measures[cache_key] = measure
        lo, hi = W._decode(measure['lower_m3']), W._decode(measure['upper_m3'])
        if not measure['met']:
            raise V.VolumeError('physical component volume did not meet the declared integration width')
        if hi == 0:
            # A curved-support proof of EXACT zero takes precedence over a
            # phantom positive planar approximation. This is not sliver culling.
            if booked is not None and booked.get(logical, Q(0)) > 0:
                raise V.VolumeError('differential thermal cell has no certified positive physical subset: '
                    'booked material occupies an exactly zero-volume component '+logical)
            continue
        if lo <= 0:
            raise V.VolumeError('differential thermal cell has no certified positive physical subset: '
                +str(dict(support_id=support.support_id, logical_cell_id=logical,
                          lower_m3=str(lo), upper_m3=str(hi), leaves=measure['leaves'])))
        poly = B._box(voxel)
        for name, sign in component['constraints']:
            normal, offset = planes[name]
            poly = B._clip(poly, (*(-sign*q for q in normal), -sign*offset), arena)
            if not poly:
                break
        angular = poly
        pieces, volume = [], Q(0)
        for tile, angular_piece in clipped_tiles(voxel, angular, subdivisions=subdivisions,
                shared_lines=shared_lines, arena=arena):
            minimum, maximum = tile._radial_bounds()
            if minimum >= layer.top_radius_m**2 or maximum <= layer.bottom_radius_m**2:
                continue
            with B._Arena(budget) as scratch:
                poly = angular_piece
                radial = E._radial_facets(tile, layer.bottom_radius_m, layer.top_radius_m)
                for plane in radial:
                    poly = B._clip(poly, plane, scratch)
                amount = B._volume(poly, scratch)
                work = scratch.work_units
            arena.work(work)
            volume += amount
            if amount and retain_polys:
                arena.keep(tuple(q for p in B._points(poly) for q in p), sum(map(len, poly)))
                pieces.append((poly, radial, amount))
        if volume == 0:
            if hi != 0:
                if missing is not None and lo > 0 and measure.get('positive_witness_point_m') is not None:
                    missing.append((voxel, _compact_witness(voxel,
                        measure['positive_witness_point_m'], component, posed, layer)))
                    continue
                raise V.VolumeError('positive or unresolved differential material has no thermal surrogate; refine geometry: '
                    +str(dict(support_id=support.support_id, logical_cell_id=logical,
                        source_key=row['source_key'], voxel_index=row.get('voxel_index'),
                        lower_m3=str(lo), upper_m3=str(hi),
                        positive_witness_m3=measure['positive_witness_m3'])))
            continue
        error = max(abs(volume-lo), abs(volume-hi))
        metadata = dict(kind='exterior', logical_cell_id=logical, source_key=row['source_key'],
            plate_id=row['plate_id'], material_support_kind=row['kind'],
            physical_support=dict(differential_support_id=support.support_id, logical_cell_id=logical),
            physical_volume_bounds_m3=list(map(E._enc, (lo, hi))),
            geometry_volume_max_deviation_m3=E._enc(error))
        for index, (poly, radial, _) in enumerate(pieces):
            result.append((logical, poly, metadata, voxel, radial, error if index == 0 else Q(0)))
    return result


def _witness_grid(supports, lines, *, endpoint, integration_width, max_leaves,
                  max_refinements, budget, arena, measures=None, booked=None):
    """Refine one continuous radial interpolant at certified interior points.

    Squared radius in an orthogonal chart is a sum of three one-dimensional
    quadratics. Inserting all coordinates of an interior point makes the
    shared interpolant exact there. Thus a certified positive physical piece
    has a positive thermal neighbourhood, without altering its real volume.
    The common axis knots prevent cracks between different source components.
    Refining an interpolant of a convex quadratic can only decrease it, while
    it remains above the true squared radius. Consequently a STRICT interior
    witness already inside the outer interpolant remains inside both radial
    bounds after later insertions. One pointwise pass suffices; repeatedly
    constructing every Cartesian product tile here serves no mathematical
    purpose and needlessly consumes the finite predicate-work allowance.
    """
    knots = [set(axis) for axis in lines]
    measures = {} if measures is None else measures
    refined = False
    for support in supports:
        row = support.record()
        posed = None if _unposed(booked, row) else (
            D.posed_support(support, endpoint=endpoint, budget=budget).record() if booked is None else
            D._mesh_posed_support(support, row, endpoint=endpoint, booked=booked, budget=budget).record())
        if posed is None:
            D._validate_unposed_support(support, row, endpoint=endpoint, budget=budget)
        box = V.CartesianCell.from_record(row['voxel'], budget=budget)
        layer = V.RadialLayer(*(W._decode(row['radial_layer'][k]) for k in
            ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        for component in row['components']:
            logical = component['logical_cell_id']
            if _unbooked(booked, logical):
                continue
            key = (support.support_id, logical, endpoint)
            measure = measures.get(key)
            if measure is None:
                measure = D.component_volume_bounds(support, logical, endpoint=endpoint,
                    max_width_m3=integration_width, max_leaves=max_leaves,
                    positive_witness=True, budget=budget).record()
                arena.stack.enter_context(budget.reserve(4096+2*_width(measure),
                    category='thermal-certified-volume-cache'))
                measures[key] = measure
            low, high = map(W._decode, (measure['lower_m3'], measure['upper_m3']))
            if not measure['met']:
                raise V.VolumeError('physical component volume did not meet the declared integration width')
            if high == 0:
                if booked is not None and booked.get(logical, Q(0)) > 0:
                    raise V.VolumeError('differential thermal cell has no certified positive physical subset: '
                        'booked material occupies an exactly zero-volume component '+logical)
                continue
            if low <= 0 or measure.get('positive_witness_point_m') is None:
                raise V.VolumeError('differential thermal cell has no certified positive physical subset: '
                    +str(dict(support_id=support.support_id, logical_cell_id=logical,
                              lower_m3=str(low), upper_m3=str(high), leaves=measure['leaves'])))
            values = tuple(map(W._decode, measure['positive_witness_point_m']))
            with V._work((*values, *box._geometry(), *layer._geometry()), budget):
                local = _compact_witness(box, measure['positive_witness_point_m'], component, posed, layer)
                physical = tuple(box.origin_m[i]+sum(box.basis[i][j]*local[j] for j in range(3))
                                 for i in range(3))
                square = O._dot(physical, physical)
                # The interpolation error is separable even for a translated,
                # rationally rotated orthogonal chart: all cross/linear terms
                # interpolate exactly. Insert the largest remaining error
                # term first, and no gratuitous extra knots.
                shared = tuple(tuple(sorted(axis)) for axis in knots)
                errors = _radial_interpolation_errors(shared, local)
                arena.work(32+sum(len(axis) for axis in shared))
                for axis in sorted(range(3), key=lambda j: errors[j], reverse=True):
                    if square+sum(errors) < layer.top_radius_m**2:
                        break
                    if max_refinements == 0:
                        raise V.VolumeError('certified-point thermal refinement ceiling reached; no material was dropped')
                    knots[axis].add(local[axis])
                    arena.keep((local[axis],), 1)
                    errors[axis] = Q(0)
                    refined = True
                if not layer.bottom_radius_m**2 < square+sum(errors) < layer.top_radius_m**2:
                    raise V.VolumeError('certified interior knot failed to produce a positive thermal cell')
    return tuple(tuple(sorted(axis)) for axis in knots), measures, int(refined)


def _radial_interpolation_errors(lines, point):
    """Exact q_h(x)-|x|² terms in an orthogonal Cartesian chart."""
    result = []
    for axis, x in zip(lines, point):
        at = bisect_right(axis, x)-1
        if at < 0 or at >= len(axis)-1:
            raise V.VolumeError('radial interpolation point is outside the shared grid interior')
        result.append((x-axis[at])*(axis[at+1]-x))
    return result


def _carry(partials, value):
    """Add one exact term to a binary counter of partial sums.

    Level k holds the sum of 2**k consecutive terms, or None. Rational
    addition is exact and associative, so the held levels add up to the same
    total as one running sum, without renormalising that long total for every
    term and without retaining the terms themselves.
    """
    for level, held in enumerate(partials):
        if held is None:
            partials[level] = value
            return
        value, partials[level] = held+value, None
    partials.append(value)


def _encode_mesh_record(record):
    """Encode the complete mesh while decoding one issued support at a time.

    Each ordinary JSON call keeps the value's original container depth, so
    nested values retain the full encoder's recursion and failure behaviour.
    Only fixed wrapper punctuation is removed; every field is encoded.
    """
    with BytesIO() as output:
        output.write(b'{')
        for at, (key, value) in enumerate(sorted(record.items())):
            if at:
                output.write(b',')
            if key != 'support_tables':
                encoded = json.dumps({key: value}, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                output.write(encoded[1:-1])
                continue
            output.write(b'"support_tables":{')
            for table_at, (name, table) in enumerate(sorted(value.items())):
                if table_at:
                    output.write(b',')
                if name != 'differential_supports':
                    encoded = json.dumps({'support_tables': {name: table}}, sort_keys=True,
                        separators=(',', ':'), allow_nan=False).encode()
                    output.write(encoded[len(b'{"support_tables":{'):-2])
                    continue
                output.write(b'"differential_supports":{')
                for support_at, (ident, support) in enumerate(sorted(table.items())):
                    if support_at:
                        output.write(b',')
                    encoded = json.dumps({'support_tables': {'differential_supports': {ident: support.record()}}},
                        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                    output.write(encoded[len(b'{"support_tables":{"differential_supports":{'):-3])
                output.write(b'}')
            output.write(b'}')
        output.write(b'}')
        return output.getvalue()


def build_differential_mesh(funding, bounds, supports, *, endpoint,
                            max_geometry_volume_error_m3, max_leaves, budget,
                            thermal_subdivisions=1, max_witness_refinements=0, closed_graph=None):
    """Build the complete endpoint mesh bound to the actual ALE inventory.

    Basal compartment exclusions are actual funded Cartesian supports. Only the
    declared open basal faces may have no neighbouring spatial thermal cell;
    both these faces and all exposed reservoir cuts require an explicit thermal
    condition from the heat caller.
    All other uncovered active-grid boundaries refuse, as on the older route.

    ``closed_graph`` is the exact carried-volume closure of these interval
    bounds. With it the cells are the components that carry booked material,
    as the heat solve requires: a component with no booked end volume gets no
    cell and is not measured, and the declared geometry error is shared among
    the booked components only, since the others have no surrogate at all.
    A support none of whose components is booked is read and its voxel and
    radial layer rebuilt, but its constraints are not posed (``_unposed``).
    Every booked component still needs its certified volume within that share
    and a certified positive subset. The closure must name these bounds by
    identity and hold every component of the supports as an active or
    inactive cell; its own identity is recorded, and the heat solve accepts
    the mesh only with that same graph. Without it nothing changes.
    """
    static = type(bounds) is D.DifferentialInitialBounds
    if (type(funding) is not FullCellFunding or type(bounds) not in (SpatialALEBounds, D.DifferentialInitialBounds) or
            type(budget) is not WorkBudget or funding._resource is not budget or bounds._resource is not budget):
        raise V.VolumeError('actual funding and issued differential ALE bounds on one budget required')
    if endpoint not in ('start', 'end') or type(supports) is not tuple or not supports:
        raise V.VolumeError('explicit endpoint and complete issued support tuple required')
    if static and endpoint != 'start':
        raise V.VolumeError('a static initial partition has no future thermal endpoint')
    if any(type(s) is not D.DifferentialSupport or s._resource is not budget for s in supports):
        raise V.VolumeError('every physical support must be issued on the shared budget')
    width = W._q(max_geometry_volume_error_m3)
    if width <= 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive predeclared geometry error and finite integration ceiling required')
    if (type(thermal_subdivisions) is not int or thermal_subdivisions < 1 or
            thermal_subdivisions & (thermal_subdivisions-1) or thermal_subdivisions**3 > max_leaves):
        raise V.VolumeError('shared dyadic thermal subdivision within the declared leaf ceiling required')
    if type(max_witness_refinements) is not int or max_witness_refinements < 0:
        raise V.VolumeError('nonnegative finite certified-point refinement ceiling required')
    if max_witness_refinements and thermal_subdivisions != 1:
        raise V.VolumeError('select shared dyadic or certified-point refinement explicitly, not both')
    f, b = funding.descriptor(), bounds.record()
    booked = None
    if closed_graph is not None:
        from .integration_spatial_ale import SpatialALEGraph
        if (static or endpoint != 'end' or type(closed_graph) is not SpatialALEGraph or
                closed_graph._resource is not budget):
            raise V.VolumeError('booked end volumes need the issued exact closure of these interval bounds')
        # The materialised closure view is temporary: it is released with this
        # reservation, and only the booked end volumes are kept for the build.
        with budget.reserve(65536+4*len(closed_graph._json), category='differential-thermal-mesh-closure-view'):
            g = closed_graph.record()
            # The closure names the bounds it closed and carries every
            # identifying field of them.
            if g.get('bounds_id') != bounds.bounds_id or any(key not in b or g.get(key) != b[key] for key in (
                    'interval_id', 'partition_id', 'parent_partition_id',
                    'funding_id', 'grid_id', 'source_flow_stage_id', 'flow_id', 'parent_state_id', 'native_measure_id',
                    'native_directed_id', 'finite_state_id', 'start_support_id', 'end_support_id',
                    'trajectory_id', 'start_time_s', 'end_time_s')):
                raise V.VolumeError('exact closure belongs to other physical interval bounds')
            booked = {row['cell_id']: W._decode(row['end_volume_m3'])
                      for row in g['cells']+g['inactive_zero_measure_cells']}
            del g
        if any(volume < 0 for volume in booked.values()):
            raise V.VolumeError('exact closure booked a negative end volume')
    ids = [s.support_id for s in supports]
    if (b.get('support_ids') != ids or len(set(ids)) != len(ids) or
            b['funding_id'] != funding.funding_id or b['source'] != f['source']):
        raise V.VolumeError('thermal support inventory differs from its complete physical ALE bounds')
    def foreign(r):
        return ((r.get('current_geometry_id') != b['current_geometry_id'] or r['start_time_s'] != b['time_s'])
                if static else (r['interval_id'] != b['interval_id'] or r[endpoint+'_time_s'] != b[endpoint+'_time_s']))
    # Preserve the original parse-before-validation failure order without
    # retaining a decoded copy of every complete support at the same time.
    # While every support parses and passes, one decode serves the interval
    # check and the component inventory. The first support that does not,
    # for any reason those two readings can raise, sends the whole inventory
    # through the three ordered passes, which alone decide the failure.
    component_ids, staged = [], False
    for support in supports:
        r = support.record()
        try:
            staged = bool(foreign(r))
            if not staged:
                component_ids.extend([c['logical_cell_id'] for c in r['components']])
        except Exception:
            staged = True
        del r
        if staged:
            break
    if staged:
        for support in supports:
            support.record()
        if any(foreign(r) for r in (s.record() for s in supports)):
            raise V.VolumeError('thermal support belongs to a different physical interval')
        component_ids = [c['logical_cell_id'] for s in supports for c in s.record()['components']]
    if len(set(component_ids)) != len(component_ids):
        raise V.VolumeError('physical logical component appears more than once')
    # A closure keeps every component of its bounds as an active or inactive
    # cell. One it does not name has no booked volume at all, which is not a
    # booked zero.
    if booked is not None and any(key not in booked for key in component_ids):
        raise V.VolumeError('exact closure does not name every physical component of these supports')
    bounded = {r['cell_id']: r for r in b['cells'] if r['kind'] == 'exterior'}
    # All-time zero components may remain only in the support certificate. A
    # positive or time-transient row may never be silently omitted from bounds.
    if set(bounded)-set(component_ids):
        raise V.VolumeError('physical ALE cell has no matching issued thermal support')
    support_id = b['support_id'] if static else b[endpoint+'_support_id']
    with budget.reserve(131072+2*funding._snapshot.nbytes+2*len(bounds._json)+
                        sum(2*len(s._json) for s in supports), category='differential-thermal-mesh'), B._Arena(budget) as arena:
        candidates, boxes, radials, groups = [], {}, {}, {}
        errors = []
        if booked is not None:
            arena.keep(tuple(booked.values()), len(booked))
        carried = (component_ids if booked is None else
                   [key for key in component_ids if not _unbooked(booked, key)])
        local_width = width/(2*max(1, len(carried)))
        shared, measures, refinements = None, None, 0
        if max_witness_refinements:
            lines = tuple(tuple(map(W._decode, axis)) for axis in b['grid_lines'])
            measures = {}
            if static:
                # One identity of the immutable issued bounds serves every row.
                bounds_id = bounds.bounds_id
                for row in bounded.values():
                    low, high = map(W._decode, row['volume_bounds_m3'])
                    if high-low <= local_width and (high == 0 or
                            low > 0 and row.get('positive_witness_point_m') is not None):
                        key = (row['support_id'], row['cell_id'], endpoint)
                        measures[key] = dict(lower_m3=row['volume_bounds_m3'][0],
                            upper_m3=row['volume_bounds_m3'][1], met=True,
                            positive_witness_m3=row['positive_witness_m3'],
                            positive_witness_point_m=row.get('positive_witness_point_m'),
                            source_initial_bounds_id=bounds_id)
                arena.stack.enter_context(budget.reserve(4096+2*_width(list(measures.values())),
                    category='thermal-certified-volume-cache'))
            shared, measures, refinements = _witness_grid(supports, lines, endpoint=endpoint,
                integration_width=local_width, max_leaves=max_leaves,
                max_refinements=max_witness_refinements, budget=budget, arena=arena, measures=measures,
                booked=booked)
        aggregate = thermal_subdivisions != 1 or shared is not None
        tables = dict(voxels={}, differential_supports={ids[at]: s for at, s in enumerate(supports)})
        native = {r['physical_cell_id']: r for r in b['cells'] if r['kind'] == 'collar'}
        for cell_record in f['cell_geometries']:
            cell = V.CartesianCell.from_record(cell_record, budget=budget)
            if cell.cell_id not in native:
                raise V.VolumeError('actual native cell is absent from the ALE inventory')
            bound = native[cell.cell_id]
            logical = bound['cell_id']
            key = E._hash(dict(logical_cell_id=logical, support_id=support_id))
            tables['voxels'][cell.cell_id] = cell.record()
            metadata = dict(kind='collar', index=bound['index'], logical_cell_id=logical,
                physical_cell_id=cell.cell_id, physical_support=dict(voxel_id=cell.cell_id),
                physical_volume_bounds_m3=[E._enc(cell.volume_m3)]*2,
                geometry_volume_max_deviation_m3=E._enc(0))
            candidates.append((key, B._box(cell), metadata)); boxes[key] = cell
        unbooked = []
        for support in supports:
            for piece, (logical, poly, metadata, box, radial, error) in enumerate(_support_cells(support,
                    endpoint=endpoint, integration_width=local_width, max_leaves=max_leaves,
                    budget=budget, arena=arena, subdivisions=thermal_subdivisions,
                    shared_lines=shared, measures=measures, booked=booked, unbooked=unbooked)):
                if logical not in bounded:
                    raise V.VolumeError('positive physical thermal component is missing from ALE bounds')
                physical = tuple(map(W._decode, bounded[logical]['volume_bounds_m3' if static else endpoint+'_volume_bounds_m3']))
                own = tuple(map(W._decode, metadata['physical_volume_bounds_m3']))
                if max(physical[0], own[0]) > min(physical[1], own[1]):
                    raise V.VolumeError('independent physical endpoint enclosures disagree')
                key = E._hash(dict(logical_cell_id=logical, support_id=support_id))
                part = key if not aggregate else E._hash(dict(cell_id=key, piece=piece))
                candidates.append((part, poly, metadata)); boxes[key] = box
                radials.setdefault(key, []).extend(radial)
                groups[part] = key
                if error:
                    _carry(errors, error)
        # The same exact total as one running sum; see _carry.
        total_error = sum((q for q in errors if q is not None), Q(0))
        if total_error > width:
            raise V.VolumeError('differential thermal surrogate exceeds declared physical geometry error')
        cells, faces = E._assemble(candidates, arena)
        if aggregate:
            cells, faces = _aggregate_cells(cells, faces, groups, boxes, arena)
        by_cell = {c['cell_id']: c for c in cells}
        basal = f.get('basal_inventory')
        native_boxes = [boxes[k] for k in by_cell if by_cell[k]['kind'] == 'collar']
        edge = None
        if basal:
            axis, end = 'xyz'.index(basal['side'][0]), int(basal['side'][1])
            edge = (min(c.lower_m[axis] for c in native_boxes) if end == 0 else
                    max(c.upper_m[axis] for c in native_boxes))
        required_thermal = []
        for face in faces:
            points = tuple(tuple(map(W._decode, p)) for p in face['vertices_m'])
            cartesian = []
            for key in face['owners']:
                box = boxes[key]
                local = tuple(tuple(sum(box.basis[i][j]*(p[i]-box.origin_m[i]) for i in range(3))
                                    for j in range(3)) for p in points)
                for j in range(3):
                    for e, coordinate in enumerate((box.lower_m[j], box.upper_m[j])):
                        if all(p[j] == coordinate for p in local):
                            cartesian.append(dict(cell_id=key, physical_voxel_id=box.cell_id,
                                axis=j, end=e, local_coordinate_m=E._enc(coordinate)))
            if cartesian:
                face.update(geometry_kind='cartesian', cartesian_support=cartesian,
                    relative_advection='actual native flow or issued component face-time measure')
            elif any(all(O._dot(p[:3], x) == p[3] for x in points)
                     for key in face['owners'] for p in radials.get(key, ())):
                face.update(geometry_kind='radial-facet',
                    relative_advection='zero on actual spherical radial interface, not surrogate facet')
            else:
                face.update(geometry_kind='differential-component-interface',
                    relative_advection='issued physical moving-interface measure, never assumed comoving')
            if len(face['owners']) == 1 and by_cell[face['owners'][0]]['kind'] == 'collar':
                if not basal or not any(p['axis'] == axis and p['end'] == end and
                        W._decode(p['local_coordinate_m']) == edge for p in cartesian):
                    raise V.VolumeError('differential exterior leaves an undeclared active-grid thermal boundary')
                face['boundary_role'] = 'finite-basal-reservoir'
                required_thermal.append(face['face_id'])
        if basal:
            required_thermal.extend(_reservoir_thermal_boundaries(faces, by_cell, native_boxes,
                dict(basal, excluded_cells=f['excluded_static_cells']), budget, arena))
        history = b['trajectory']['segments']
        segments = history if static or endpoint == 'end' else history[:-1]
        trajectory_id = b['trajectory_id' if static or endpoint == 'end' else 'prior_trajectory_id']
        if E._hash(segments) != trajectory_id:
            raise V.VolumeError('physical trajectory prefix identity differs')
        record = dict(schema='atlas.source-bound-exterior-thermal-mesh.v1', method=E.METHOD,
            physical_geometry_family='differential-plate-component-partition-v1',
            funding_id=funding.funding_id, source=f['source'], support_id=support_id,
            trajectory_id=trajectory_id, trajectory_segments=segments, endpoint=endpoint,
            support_ids=ids,
            time_s=b['time_s'] if static else b[endpoint+'_time_s'], grid_id=b['grid_id'], grid_lines=b['grid_lines'],
            cells=cells, faces=faces, support_tables=tables,
            required_thermal_boundary_faces=sorted(required_thermal),
            geometry_volume_max_deviation_m3=E._enc(total_error), max_geometry_volume_error_m3=E._enc(width),
            radial_rule='continuous piecewise-affine Cartesian interpolant of squared radius',
            scope='thermal metrics on actual material components; no physical volume replacement or stock creation')
        if booked is not None:
            record['booked_cell_rule'] = dict(closed_graph_id=closed_graph.geometry_id,
                booked_components=len(carried), components_without_booked_material=len(unbooked),
                rule='cells are the components with a positive exactly booked end volume; the others are not '
                     'measured and have no surrogate; the geometry error is shared among booked components')
        if static:
            record.update(current_geometry_id=b['current_geometry_id'], partition_id=b['partition_id'],
                          initial_bounds_id=bounds.bounds_id)
        else:
            record.update(interval_id=b['interval_id'], ale_bounds_id=bounds.bounds_id,
                          partition_id=b['partition_id'], parent_partition_id=b['parent_partition_id'])
        if thermal_subdivisions != 1:
            record['thermal_subdivisions'] = thermal_subdivisions
        if shared is not None:
            record['thermal_shared_lines'] = [list(map(E._enc, axis)) for axis in shared]
            record['thermal_witness_refinements'] = refinements
            record['max_thermal_witness_refinements'] = max_witness_refinements
        if aggregate:
            record['thermal_aggregation'] = 'exact same-physical-cell volume/moments and internal-facet cancellation'
        encoded = _encode_mesh_record(record)
        lease = budget.reserve(8192+4*len(encoded), category='differential-thermal-mesh-retained')
        lease.__enter__()
        try:
            result = object.__new__(E.ExteriorMesh)
            object.__setattr__(result, '_json', encoded); object.__setattr__(result, '_resource', budget)
            weakref.finalize(result, lease.__exit__, None, None, None)
            return result
        except BaseException:
            lease.__exit__(None, None, None)
            raise
