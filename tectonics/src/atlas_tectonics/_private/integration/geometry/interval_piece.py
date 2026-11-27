"""Uninstalled nominal END-piece construction for source comparison.

The caller owns certified physical witnesses, inventory and charge accounting.
This helper does not issue a mesh, authorise a booking, or prove coverage.
"""
from fractions import Fraction as Q


def build_piece(support, logical_id, tile, grid, booked, interval_rays, context,
                *, budget, arena, D, V, B, E, W):
    if logical_id not in booked or booked[logical_id] < 0:
        raise ValueError('logical booking missing or negative '+logical_id)
    row = support.record()
    if (row['interval_id'] != interval_rays.interval.interval_id or
        row['grid_id'] != context.frame or row['plate_id'] not in interval_rays.record['plate_angular_velocity_rad_s'] or
        tuple(map(W._decode,row['material_angular_velocity_rad_s'])) != context.omega or
        W._decode(row['start_time_s']) != context.start or W._decode(row['end_time_s']) != context.end):
        raise ValueError('support interval/material context differs '+logical_id)
    found = [part for part in row['components'] if part['logical_cell_id'] == logical_id]
    component = found[0]
    V.CartesianCell.from_record(row['voxel'], budget=budget)
    for j, axis in enumerate(grid):
        try:
            lower = axis.index(tile.lower_m[j])
            upper = axis.index(tile.upper_m[j])
        except ValueError:
            raise ValueError('tile boundary missing from shared grid '+logical_id) from None
        if upper != lower+1:
            raise ValueError('tile spans multiple grid intervals '+logical_id)
    path = component['partition_path']
    fans = [r['ray_ids'] for r in interval_rays.record['ownership_fans'] if r['plate_id'] == row['plate_id']]
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
        literal = row['constraints'][name]
        if name.startswith('owner:'):
            legacy = name.count('>') > 1 and not name.startswith('owner:>')
            indexes = [i for i,(a,b) in enumerate(pairs) if name ==
                       ('owner:'+a+'>'+b if legacy else D._directed_edge_name('owner', a, b))]
            normal, error, offset = owner[indexes[0]]
        elif literal['kind'] == 'fixed-plane':
            normal, error, offset = D._constraint_pose(literal,context.duration,context.duration,24,arena)
            normal, offset = tuple(sign*x for x in normal), sign*offset
        else:
            old = D._constraint_pose(literal,context.duration,context.duration,24,arena)
            key = context.start_and_key(literal)
            value, changed = context.place(literal,{key[0]},old,expected=True)
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
