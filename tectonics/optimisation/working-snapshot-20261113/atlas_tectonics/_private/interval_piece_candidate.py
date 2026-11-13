"""Uninstalled nominal END-piece construction for source comparison.

The caller owns certified physical witnesses, inventory and charge accounting.
This helper does not issue a mesh, authorise a booking, or prove coverage.
"""
from fractions import Fraction as Q


def build_piece(support, logical_id, tile, grid, booked, interval_rays, context,
                *, budget, arena, D, V, B, E, W):
    if (type(support) is not D.DifferentialSupport or support._resource is not budget or
        type(tile) is not V.CartesianCell or tile._resource is not budget or
        arena.resource is not budget or interval_rays.arena.resource is not budget or
        context.arena.resource is not budget):
        raise ValueError('issued support and one shared resource required')
    if logical_id not in booked or booked[logical_id] < 0:
        raise ValueError('logical booking missing or negative '+logical_id)
    row = support.record()
    if (row['interval_id'] != interval_rays.interval.interval_id or
        row['grid_id'] != context.frame or row['plate_id'] not in interval_rays.record['plate_angular_velocity_rad_s'] or
        tuple(map(W._decode,row['material_angular_velocity_rad_s'])) != context.omega or
        W._decode(row['start_time_s']) != context.start or W._decode(row['end_time_s']) != context.end):
        raise ValueError('support interval/material context differs '+logical_id)
    found = [part for part in row['components'] if part['logical_cell_id'] == logical_id]
    if len(found) != 1:
        raise ValueError('logical component missing or duplicated '+logical_id)
    component = found[0]
    box = V.CartesianCell.from_record(row['voxel'], budget=budget)
    if (tile.origin_m != box.origin_m or tile.basis != box.basis or len(grid) != 3 or
        any(not box.lower_m[j] <= tile.lower_m[j] < tile.upper_m[j] <= box.upper_m[j] for j in range(3))):
        raise ValueError('tile frame or support containment differs '+logical_id)
    for j, axis in enumerate(grid):
        if any(a >= b for a,b in zip(axis,axis[1:])):
            raise ValueError('shared grid is not strictly increasing')
        if tile.lower_m[j] not in axis or tile.upper_m[j] not in axis:
            raise ValueError('tile boundary missing from shared grid '+logical_id)
        if axis.index(tile.upper_m[j]) != axis.index(tile.lower_m[j])+1:
            raise ValueError('tile spans multiple grid intervals '+logical_id)
    path = component['partition_path']
    fans = [r['ray_ids'] for r in interval_rays.record['ownership_fans'] if r['plate_id'] == row['plate_id']]
    if (len(path) < 2 or path[0] != 'owner-fan' or type(path[1]) is not int or
        not 0 <= path[1] < len(fans) or component['owner_ray_ids'] != fans[path[1]]):
        raise ValueError('issued owner path differs '+logical_id)
    fan = fans[path[1]]
    pairs = list(zip(fan,fan[1:]+fan[:1]))
    cache = getattr(interval_rays, '_piece_owner_planes', None)
    if cache is None:
        cache = {}
        interval_rays._piece_owner_planes = cache
    cache_key = (row['plate_id'], tuple(fan))
    if cache_key not in cache:
        value = tuple(interval_rays.edge(a,b) for a,b in pairs)
        interval_rays.arena.keep(tuple(q for n,e,d in value for q in (*n,e,d)),objects=1)
        cache[cache_key] = value
    owner = cache[cache_key]
    cuts = []
    for name, sign in component['constraints']:
        if sign not in (-1,1):
            raise ValueError('invalid signed literal '+logical_id+' '+name)
        literal = row['constraints'][name]
        if name.startswith('owner:'):
            indexes = [i for i,(a,b) in enumerate(pairs) if name == 'owner:'+a+'>'+b]
            if len(indexes) != 1 or sign != 1:
                raise ValueError('owner literal does not match issued fan '+logical_id+' '+name)
            normal, error, offset = owner[indexes[0]]
        elif literal['kind'] == 'fixed-plane':
            normal, error, offset = D._constraint_pose(literal,context.duration,context.duration,24,arena)
            normal, offset = tuple(sign*x for x in normal), sign*offset
        else:
            old = D._constraint_pose(literal,context.duration,context.duration,24,arena)
            key = context.start_and_key(literal)
            if key is None:
                raise ValueError('unproved material literal '+logical_id+' '+name)
            value, changed = context.place(literal,{key[0]},old,expected=True)
            if not changed:
                raise ValueError('material placement refused '+logical_id+' '+name)
            normal, error, offset = value
            normal, offset = tuple(sign*x for x in normal), sign*offset
        cuts.append((normal,error,offset))
    cuts.extend(owner)
    layer = V.RadialLayer(*(W._decode(row['radial_layer'][k]) for k in
                            ('radius_m','top_depth_m','bottom_depth_m')),budget=budget)
    piece = B._box(tile)
    for normal, error, offset in cuts:
        piece = B._clip(piece,tuple(-x for x in normal)+(-offset,),arena)
        if not piece:
            break
    for plane in E._radial_facets(tile,layer.bottom_radius_m,layer.top_radius_m):
        if not piece:
            break
        piece = B._clip(piece,plane,arena)
    volume = B._volume(piece,arena) if piece else Q(0)
    if volume < 0:
        raise ValueError('negative nominal tile volume '+logical_id)
    return dict(logical_id=logical_id,support_id=support.support_id,source_chart_id=row['source_chart_id'],
                source_key=row['source_key'],plate_id=row['plate_id'],path=tuple(path),
                booking=booked[logical_id],poly=piece,volume=volume)
