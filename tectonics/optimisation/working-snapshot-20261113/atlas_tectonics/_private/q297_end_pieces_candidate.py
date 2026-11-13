"""Uninstalled per-support END piece construction for q297 preparation.

This helper consumes issued supports and the previously authenticated nominal
totals. It does not issue a closure or mesh, or prove face incidence. The
caller owns source selection, interval/funding/closure bindings, budgets and
the lifetime of the supplied arena and candidate contexts.
"""
from fractions import Fraction as Q


def _actual_planes(row, component, rays, context, *, D, W):
    issue = rays.record
    path = component['partition_path']
    fans = [r['ray_ids'] for r in issue['ownership_fans'] if r['plate_id'] == row['plate_id']]
    if (len(path) < 2 or path[0] != 'owner-fan' or type(path[1]) is not int or
            not 0 <= path[1] < len(fans) or component['owner_ray_ids'] != fans[path[1]]):
        raise ValueError('issued owner path differs ' + component['logical_cell_id'])
    fan = fans[path[1]]
    pairs = list(zip(fan, fan[1:] + fan[:1], strict=True))
    owner = [rays.edge(a, b) for a, b in pairs]
    cuts = []
    for name, sign in component['constraints']:
        if sign not in (-1, 1):
            raise ValueError('invalid signed material literal')
        literal = row['constraints'][name]
        if name.startswith('owner:'):
            indexes = [i for i, (a, b) in enumerate(pairs) if name == 'owner:' + a + '>' + b]
            if len(indexes) != 1 or sign != 1:
                raise ValueError('issued current-owner literal differs')
            normal, error, offset = owner[indexes[0]]
        else:
            old = D._constraint_pose(literal, context.duration, context.duration, 24, context.arena)
            if literal['kind'] == 'fixed-plane':
                normal, error, offset = old
            else:
                key = context.start_and_key(literal)
                if key is None:
                    raise ValueError('unproved material literal')
                value, changed = context.place(literal, {key[0]}, old, expected=True)
                if not changed:
                    raise ValueError('material placement refused')
                normal, error, offset = value
            normal, offset = tuple(sign * x for x in normal), sign * offset
        cuts.append((normal, error, offset))
    return cuts + owner


def _require_compact_witness(box, layer, component, posed, measure, grid, cuts, *, H, W):
    point = H._compact_witness(box, measure['positive_witness_point_m'], component, posed, layer)
    if not all(a < x < b for x, a, b in zip(point, box.lower_m, box.upper_m, strict=True)):
        raise ValueError('compact witness is outside its physical voxel')
    world = tuple(box.origin_m[i] + sum(box.basis[i][j] * point[j] for j in range(3)) for i in range(3))
    square = sum(x * x for x in world)
    interpolated = square + sum(H._radial_interpolation_errors(grid, point))
    magnitude = sum(map(abs, world))
    if (not layer.bottom_radius_m**2 < square < layer.top_radius_m**2 or
            not layer.bottom_radius_m**2 < interpolated < layer.top_radius_m**2 or
            any(sum(a * b for a, b in zip(normal, world, strict=True)) - offset - error * magnitude <= 0
                for normal, error, offset in cuts)):
        raise ValueError('compact physical witness is not strictly inside candidate and grid')


def build_support_pieces(support, *, endpoint, integration_width, max_leaves, budget, arena,
                         subdivisions, shared_lines, measures, booked, unbooked,
                         interval_rays, context, nominal_totals, piece_builder, D, H, W, V, B, E):
    """Construct H-shaped ordered pieces; caller must separately bind all inputs."""
    if (endpoint != 'end' or subdivisions != 1 or type(support) is not D.DifferentialSupport or
            support._resource is not budget or arena.resource is not budget or
            interval_rays.arena.resource is not budget or context.arena.resource is not budget or
            type(booked) is not dict or type(nominal_totals) is not dict or shared_lines is None):
        raise ValueError('issued shared-budget END support and reviewed grid required')
    row = support.record()
    if row['interval_id'] != interval_rays.interval.interval_id:
        raise ValueError('support belongs to another interval')
    if any(part['logical_cell_id'] not in booked for part in row['components']):
        raise ValueError('issued component is missing from the closure booking')
    voxel = V.CartesianCell.from_record(row['voxel'], budget=budget)
    layer = V.RadialLayer(*(W._decode(row['radial_layer'][key]) for key in
                            ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    active = [part for part in row['components'] if not H._unbooked(booked, part['logical_cell_id'])]
    if not active:
        D._validate_unposed_support(support, row, endpoint=endpoint, budget=budget)
        if unbooked is not None:
            unbooked.extend(part['logical_cell_id'] for part in row['components'])
        return []
    posed = D._mesh_posed_support(support, row, endpoint=endpoint, booked=booked, budget=budget).record()
    results = []
    for component in row['components']:
        logical = component['logical_cell_id']
        if H._unbooked(booked, logical):
            if unbooked is not None:
                unbooked.append(logical)
            continue
        if logical not in nominal_totals:
            raise ValueError('booked logical component lacks a qualified nominal total')
        cache_key = (support.support_id, logical, endpoint)
        measure = None if measures is None else measures.get(cache_key)
        if measure is None:
            measure = D.component_volume_bounds(support, logical, endpoint=endpoint,
                max_width_m3=integration_width, max_leaves=max_leaves,
                positive_witness=True, budget=budget).record()
            if measures is not None:
                measures[cache_key] = measure
        lo, hi = W._decode(measure['lower_m3']), W._decode(measure['upper_m3'])
        if not measure['met'] or lo <= 0 or hi < lo or not measure.get('positive_witness_point_m'):
            raise ValueError('booked component lacks a certified positive physical enclosure and witness')
        cuts = _actual_planes(row, component, interval_rays, context, D=D, W=W)
        _require_compact_witness(voxel, layer, component, posed, measure, shared_lines, cuts, H=H, W=W)
        pieces = []
        volume = Q(0)
        with B._Arena(budget) as walk:
            for tile, _ in H.clipped_tiles(voxel, B._box(voxel), subdivisions=subdivisions,
                                           shared_lines=shared_lines, arena=walk):
                low, high = tile._radial_bounds()
                if low >= layer.top_radius_m**2 or high <= layer.bottom_radius_m**2:
                    continue
                with B._Arena(budget) as scratch:
                    built = piece_builder.build_piece(support, logical, tile, shared_lines, booked,
                        interval_rays, context, budget=budget, arena=scratch, D=D, V=V, B=B, E=E, W=W)
                    if (built['logical_id'] != logical or built['support_id'] != support.support_id or
                            built['source_chart_id'] != row['source_chart_id'] or
                            built['source_key'] != row['source_key'] or built['plate_id'] != row['plate_id'] or
                            built['path'] != tuple(component['partition_path']) or built['booking'] != booked[logical]):
                        raise ValueError('returned piece ownership or booking differs')
                    amount = built['volume']
                    if amount:
                        poly = built['poly']
                        radial = E._radial_facets(tile, layer.bottom_radius_m, layer.top_radius_m)
                        arena.keep(tuple(q for p in B._points(poly) for q in p), sum(map(len, poly)))
                        arena.keep(tuple(q for plane in radial for q in plane), len(radial))
                        pieces.append((poly, radial))
                        volume += amount
                        arena.keep((amount, volume), 2)
                    walk.work(scratch.work_units)
            arena.work(walk.work_units)
        if volume <= 0 or volume != nominal_totals[logical]:
            raise ValueError('candidate nominal total differs from the authenticated full sweep')
        error = max(abs(volume - lo), abs(volume - hi))
        metadata = dict(kind='exterior', logical_cell_id=logical, source_key=row['source_key'],
            plate_id=row['plate_id'], material_support_kind=row['kind'],
            physical_support=dict(differential_support_id=support.support_id, logical_cell_id=logical),
            physical_volume_bounds_m3=list(map(E._enc, (lo, hi))),
            geometry_volume_max_deviation_m3=E._enc(error))
        for index, (poly, radial) in enumerate(pieces):
            results.append((logical, poly, metadata, voxel, radial, error if index == 0 else Q(0)))
    return results
