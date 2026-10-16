"""Source-issued differential physical space-time FV graph bounds.

Actual prescribed plate paths, carried convex charts and corrected mechanical
Q2 wall fields share one graph. Curved geometry remains bounded explicitly;
no thermal facet or endpoint resampling supplies a material flux.

Every exterior component surface has ONE owner. A fixed voxel wall transfers
material between the same carried shape in two voxels. Where a stationary
finite plate boundary lies exactly in such a wall, the component ends there:
that surface is its angular boundary face and is measured and routed once, by
the boundary's own declared ridge/trench inventory, never also as a Cartesian
neighbour transfer.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from fractions import Fraction as Q
from itertools import islice, product
from time import perf_counter

from . import integration_differential_geometry as D
from .integration_component_volume_batch import ComponentVolumeQueries
from . import integration_spatial_ale as A
from . import integration_native_faces as N
from . import integration_native_projection as P
from . import integration_parallel_selection as S
from . import integration_component_volume_auto as E
from . import integration_volume as V
from . import integration_wall_measures as W
from .integration_collar_geometry import FullCellFunding
from .integration_spatial_reservoir import FiniteStockState
from .integration_regional_inventory import _width
from .integration_routing_views import RoutingArena, SupportRoutingRows
from .resources import WorkBudget


def _pair(record, name):
    return tuple(map(W._decode, record[name]))


def _inside(a, b):
    return (a.origin_m == b.origin_m and a.basis == b.basis and
            all(b.lower_m[j] <= a.lower_m[j] and a.upper_m[j] <= b.upper_m[j] for j in range(3)))


def _unmet_measure_error(row, support_rows, budget):
    error = V.VolumeError('differential physical integration did not meet its declared width/leaf bound')
    try:
        error.physical_measure_failure = dict(measure=row,
            supports=[support_rows[key] for key in
                (row.get('support_id'), row.get('other_support_id')) if key in support_rows])
        if row.get('kind') == 'component-fixed-voxel-face' and row.get('support_id') in support_rows:
            query = dict(logical_cell_id=row['logical_cell_id'], axis=row['axis'], end=row['end'],
                endpoint=None, moment_polynomials=row['moment_polynomials'],
                max_moment_widths=row['max_widths'][2:], max_width_m3=row['max_width_m3'],
                max_leaves=row['max_leaves'])
            if 'normal_polynomial' in row:
                query['normal_polynomial'] = row['normal_polynomial']
            error.component_moment_failure = D._wall_failure_payload(support_rows[row['support_id']],
                query, budget, error, measure=row, budget_scope='ALE arena live; component integration finished')
    except Exception as capture_error:
        _capture_incomplete(error, capture_error)
    error.add_note('kind='+str(row.get('kind'))+' logical_cell_id='+str(row.get('logical_cell_id'))+
                   ' leaves='+str(row.get('leaves')))
    return error


def _capture_incomplete(error, capture_error):
    # A secondary codec/allocation error is not the primary physical refusal.
    # Explicitly incomplete evidence must never masquerade as a replay record.
    error.diagnostic_capture_failure = dict(complete=False,
        exception_type=type(capture_error).__name__, message=str(capture_error))
    error.add_note('complete replay capture failed: '+str(capture_error))


def _native_mask_leaf_limit(max_leaves, max_native_mask_leaves):
    if max_native_mask_leaves is not None and (
            type(max_native_mask_leaves) is not int or max_native_mask_leaves < 1):
        raise V.VolumeError('native mask leaf ceiling must be an explicit positive integer or None')
    return max_leaves if max_native_mask_leaves is None else max_native_mask_leaves


def _physical_boundary_index(step):
    result = {}
    for boundary in step['boundary_paths']:
        chain = boundary['vertex_ids']+boundary['vertex_ids'][:1] if boundary['closed'] else boundary['vertex_ids']
        for first, second in zip(chain, chain[1:]):
            identity = D._interface_identity(dict(kind='moving-ray-edge',
                rays=[step['rays']['vertex:'+first], step['rays']['vertex:'+second]]))
            if identity is not None:
                result.setdefault(identity[0], []).append(boundary)
    return result


def _coincident_boundary_faces(row, part, voxel, axis, end, boundaries):
    """Angular finite-boundary faces that ARE this fixed voxel face.

    An exact whole-interval identity, never a small-flux exemption. The wall
    must pass through the sphere centre; a non-material moving-ray plane of the
    component must be stationary (no rate and no prior rotation, other than
    about its own normal, which leaves the plane fixed) and exactly parallel
    to it; and that literal must keep the voxel's interior side. Wall and
    literal then bound the component on one oriented surface which does not
    move, so the flux relative to either is the same material flux: one
    physical stream, owned by the angular boundary. A tilt, offset, rate or
    earlier rotation of any size is not coincidence. Every coincident literal
    needs its own unique ridge/trench authority for this plate; otherwise
    nothing is owned and the wall keeps its existing fail-closed route, as
    internal fan separators and the reversed (exterior) orientation do.
    """
    face = W._face(voxel, axis, end)
    # Angular interfaces pass through the sphere origin, not the local origin.
    if D.O._dot(face[3], face[0]):
        return ()
    omega = D._load_vec(row['material_angular_velocity_rad_s'])
    found = []
    for name, sign in part['constraints']:
        constraint_owner = owned_constraint(row['constraints'][name])
        constraint = constraint_owner.value
        if constraint['kind'] != 'moving-ray-edge' or D._material_plane(constraint, omega):
            continue
        path = D._rigid_plane_path(constraint)
        if path is None:
            continue
        normal, history, velocity = path
        if (any(history) or any(velocity) or any(D.O._cross(normal, face[3])) or
                sign*D.O._dot(normal, face[3]) >= 0):
            continue
        candidates = {b['boundary_id'] for b in boundaries.get(D._interface_identity(constraint)[0], ())
                      if b['kind'] in ('ridge', 'trench') and
                      row['plate_id'] in (b['left_plate_id'], b['right_plate_id'])}
        if len(candidates) != 1:
            return ()
        found.append(dict(logical_cell_id=part['logical_cell_id'], constraint_name=name,
            axis=axis, end=end, boundary_id=next(iter(candidates)),
            voxel_index=row['voxel_index'], physical_cell_id=voxel.cell_id,
            rule='exact stationary world-plane coincidence; angular finite-boundary ownership'))
    return tuple(found)


def _missing_neighbour_error(donor, receiver, bounds, identity, metadata, cells, supports, receipts):
    error = V.VolumeError('positive physical stream has no actual represented neighbour')
    present = [cells[key] for key in (donor, receiver) if key in cells]
    support_ids = {cell.get('support_id') for cell in present}
    try:
        error.physical_stream_failure = dict(donor=donor, receiver=receiver,
            volume_bounds_m3=list(map(D._qtext, bounds)), face_identity=identity, metadata=metadata,
            cells=present, supports=[supports[key] for key in support_ids if key in supports],
            measure=receipts.get(metadata.get('physical_certificate_id')))
    except Exception as capture_error:
        _capture_incomplete(error, capture_error)
    error.add_note('face_identity='+str(identity)+' donor='+str(donor)+' receiver='+str(receiver))
    return error


def _paired_port_streams(row, positive):
    """Lower end and shared width of one native directed stream of a wall.

    The native quadrature encloses the two opposed streams of a face as ONE
    family: N=q and P=q+n with the exact signed volume n and a common
    counterflow q in [low, high]. Its published values are the midpoint of
    that family, not exact streams. A port therefore carries the family's
    lower end exactly, and the pair of ports of one face shares a bypass of
    capacity high-low (inward port to outward port). Any bypass flow raises
    both streams equally: the native cell still exchanges exactly n, and the
    exterior may take any member of the certified family. Publishing the
    midpoint as exact refused as soon as the component enclosures of the same
    streams became narrower than the family.
    """
    low, high = map(W._decode, row['positive_volume_bounds_m3' if positive else 'negative_volume_bounds_m3'])
    other = tuple(map(W._decode, row['negative_volume_bounds_m3' if positive else 'positive_volume_bounds_m3']))
    if low < 0 or high < low or other[1]-other[0] != high-low:
        raise V.VolumeError('native directed streams are not one paired counterflow family')
    return low, high-low


class _Streams:
    """Directed physical streams and finite exchanges of one enclosure."""
    def __init__(self, cells, supports, receipts, keep):
        self.cells, self.supports, self.receipts, self.keep = cells, supports, receipts, keep
        self.faces, self.exchanges = [], []

    def add(self, donor, receiver, bounds, identity, **metadata):
        lo, hi = bounds
        if lo < 0 or hi < lo:
            raise V.VolumeError('invalid directed physical-volume interval')
        if hi:
            if donor is None or receiver is None:
                raise _missing_neighbour_error(donor, receiver, bounds, identity, metadata,
                    self.cells, self.supports, self.receipts)
            self.faces.append(dict(face_id=W._hash(identity), donor=donor, receiver=receiver,
                volume_bounds_m3=list(map(D._qtext, bounds)), **metadata))
            self.keep(self.faces[-1])

    def exchange(self, stock, physical, direction, bounds, certificate, identity):
        if not bounds[1]:
            return
        if stock is None or stock['kind'] not in ('reservoir', 'source' if direction == 'supply' else 'sink'):
            raise V.VolumeError('actual physical stream lacks a direction-compatible finite inventory')
        self.exchanges.append(dict(stock_id=stock['stock_id'], physical_cell_id=physical, direction=direction,
            face_id=W._hash(identity), volume_bounds_m3=list(map(D._qtext, bounds)),
            physical_certificate_id=certificate, stock_lineage=stock['lineage']))
        self.keep(self.exchanges[-1])


def _native_port(ports, streams, selected, boundary_faces, native_ids, directed_id, flat, axis, end, inward):
    """Algebraic port of one direction of a native boundary face, wired once.

    ``ports`` maps (native index, axis, end, inward) to the issued port cell;
    ``selected`` holds the native directed rows by face and ``boundary_faces``
    the native face of (native index, axis, end). A new port joins the cells
    of ``streams`` and carries the lower end of its own directed stream as an
    exact total between itself and the native cell. The second port of a face
    also adds the one bypass of the pair, from the inward to the outward port
    with capacity high-low; a family of zero width has none. Returns the
    identity of the port cell.
    """
    cells, keep, add = streams.cells, streams.keep, streams.add
    token = flat, axis, end, inward
    if token not in ports:
        row = selected[boundary_faces[flat, axis, end]['face_id']]
        # Increasing native normal is inward on low, outward on high.
        positive = inward == (end == 0)
        value, width = _paired_port_streams(row, positive)
        key = W._hash(dict(collar=native_ids[flat], axis=axis, end=end, inward=inward))
        ports[token] = key
        cells[key] = dict(cell_id=key, kind='algebraic-port', collar_cell_id=native_ids[flat],
            start_volume_bounds_m3=[D._qtext(Q(0))]*2, end_volume_bounds_m3=[D._qtext(Q(0))]*2)
        keep(cells[key])
        donor, receiver = (key, native_ids[flat]) if inward else (native_ids[flat], key)
        add(donor, receiver, (value, value), dict(port=key, total=True), partition_total=True,
            native_face_id=row['face_id'], native_directed_id=directed_id)
        twin = ports.get((flat, axis, end, not inward))
        if twin is not None:
            # One common counterflow of the pair, never two free streams.
            into, out = (key, twin) if inward else (twin, key)
            add(into, out, (Q(0), width), dict(port_pair=[into, out], counterflow=True), partition_total=True,
                native_face_id=row['face_id'], native_directed_id=directed_id)
    return ports[token]


def _segment_identity(plane):
    """Canonical text of one angular interface: the physical boundary segment.

    ``plane`` is the orientation-free key of ``_interface_identity``: a rigid
    homogeneous plane (unit-first normal, prior rotation, rate) or the two
    rays of a deforming edge in canonical order, which that key holds as the
    bytes of their ASCII JSON text. Reversing the rays or the literal's name
    therefore gives the same segment.
    """
    kind, value = plane
    return [kind, value.decode('ascii') if kind != 'rigid' else [list(map(D._qtext, vector)) for vector in value]]


def _exterior_interface_jobs(components, groups, owned):
    """Yield optional metadata in the physical router's unchanged visit order.

    The session bounds consumption and owns any planning storage. No physical
    query or validation is moved here; an upcoming ownership conflict stops
    lookahead and is raised only when the real routing loop reaches it.
    """
    for entries in groups.values():
        # Bound speculative scans; the actual router still visits every group.
        if len(entries) > 64:
            continue
        handled = set()
        for key, name, sign in entries:
            support = components[key][0]
            if any(s == -sign for _, _, s in entries):
                if (key, name) in owned:
                    return
                for other, _, other_sign in entries:
                    if other_sign != -sign:
                        continue
                    token = tuple(sorted((key, other)))
                    if token in handled:
                        continue
                    handled.add(token)
                    yield support, key, name, dict(other_support=components[other][0],
                                                  other_logical_cell_id=other)
                continue
            yield support, key, name, {}


def _exterior_wall_events(components, component_keys, boxes, native_at, excluded_at, boundaries):
    """Lazy wall metadata in physical visit order, with deferred validation errors.

    Bounded lookahead may inspect later metadata but must not raise its error
    before the real router has measured and routed the preceding walls.
    Ownership changes remain in that router, never in this iterator.
    """
    for key, (support, row, part) in components.items():
        try:
            at = tuple(row['voxel_index'])
            shape_key = row['source_chart_id'], tuple(part['partition_path'])
        except Exception as error:
            yield dict(error=error)
            return
        for axis, end in product(range(3), (0, 1)):
            try:
                neighbour = list(at); neighbour[axis] += 1 if end else -1; neighbour = tuple(neighbour)
                native = native_at.get(neighbour) is not None
                other = None if native else component_keys.get((neighbour, shape_key))
                stock = None if native else excluded_at.get(neighbour)
                found = _coincident_boundary_faces(row, part, boxes[at], axis, end, boundaries)
                query = not (native or other is not None and key > other or
                             found and other is None and stock is None)
                yield dict(key=key, support=support, axis=axis, end=end, native=native,
                           other=other, stock=stock, found=found, query=query)
            except Exception as error:
                yield dict(error=error)
                return


def _wall_event_batch(events, controller):
    """Bound both useful queries and metadata, retaining physical visit order."""
    if controller is None:
        return list(islice(events, 1))
    batch, queries = [], 0
    # A usual component has six faces. Sparse native-only spans still flush
    # after this cap rather than accumulating a world-sized routing history.
    for event in islice(events, 6*controller.limit):
        batch.append(event)
        if 'error' in event:
            break
        queries += bool(event['query'])
        if queries == controller.limit:
            break
    return batch


def _wall_windows(events, controller):
    """Wall event windows in the physical visit order, for the router to walk.

    A rolling controller is shown a bounded number of later windows before
    the router reaches them: metadata only, in order, each window once. The
    bound is in windows, whatever they hold: a window without a query makes
    no schedule less hungry. A deferred metadata error ends that lookahead
    like the end of the walls and is raised only when the real router
    reaches it.
    """
    offer = getattr(controller, 'offer', None)
    ahead = getattr(controller, 'ahead', 1)
    waiting = deque()
    while True:
        # Always the window the router needs next; more only while the controller asks.
        while not waiting or offer is not None and len(waiting) < ahead and controller.hungry():
            batch = _wall_event_batch(events, controller)
            if not batch:
                break
            waiting.append(batch)
            if offer is not None:
                offer(batch)
        if not waiting:
            return
        yield waiting.popleft()


def _route_exterior_surfaces(components, component_keys, boxes, native_at, excluded_at, boundaries,
                             stocks, streams, *, wall, interface, _parallel=None, _observer=None):
    """Measure and route every exterior component surface exactly once.

    ``wall(support, key, axis, end)`` and ``interface(support, key, name,
    **pair)`` issue the enclosure's own physical measures and return
    (certificate id, record). Fixed voxel walls are routed first; a wall that
    IS a finite plate boundary is left to the angular pass, which must then
    supply that same surface's unpaired certificate and boundary routing.
    Where the far side of such a wall is itself represented (native cell,
    same-shape neighbour or basal compartment) the wall keeps that route, and
    the boundary face must then carry no angular stream at all.
    An observer is told the elapsed seconds of each measure, and which
    contacts the lookahead offers, for scheduling only: it reads the returned
    record and that lazy metadata, decides nothing and changes nothing.
    Returns the resolved ownership rows.
    """
    add, exchange = streams.add, streams.exchange
    owned, resolved, represented = {}, {}, set()
    second = V.VolumeError('a finite plate boundary lying in a fixed voxel wall also has a '
                           'represented neighbour there; one physical owner is required')
    # Physical fixed-voxel faces. Process each exterior/exterior pair once;
    # native contacts were already measured with solved Q2, never rigid Ω.
    wall_batches = S.open_wall_batches(_observer, components, boxes)
    events = _exterior_wall_events(components, component_keys, boxes, native_at, excluded_at, boundaries)
    try:
        for batch in _wall_windows(events, wall_batches):
            if wall_batches is not None:
                wall_batches.prepare((event['support'], event['key'], event['axis'], dict(end=event['end']))
                                     for event in batch if 'error' not in event and event['query'])
            for event in batch:
                if 'error' in event:
                    raise event['error']
                key, support, axis, end = (event[name] for name in ('key', 'support', 'axis', 'end'))
                native, other, stock, found = (event[name] for name in ('native', 'other', 'stock', 'found'))
                if found and (native or other is not None or stock is not None):
                    # Keep this represented route; a second angular owner is
                    # still refused only when the physical router reaches it.
                    represented.update((key, ownership['constraint_name']) for ownership in found)
                elif found:
                    for ownership in found:
                        token = key, ownership['constraint_name']
                        if token in owned:
                            raise V.VolumeError('one angular boundary cannot own two distinct fixed voxel faces')
                        owned[token] = ownership
                    continue
                if native or other is not None and key > other:
                    continue
                if wall_batches is not None:
                    wall_batches.begin_wall()
                begun = None if _observer is None else perf_counter()
                ident, measured = wall(support, key, axis, end)
                if _observer is not None:
                    seconds = perf_counter()-begun
                    _observer.wall(measured, seconds)
                    if wall_batches is not None:
                        wall_batches.wall(key, axis, end, measured, seconds)
                inward, outward = (_pair(measured, name) for name in ('inward_volume_bounds_m3', 'outward_volume_bounds_m3'))
                if stock is not None:
                    exchange(stock, key, 'supply', inward, ident, dict(component=key, axis=axis, end=end, direction='supply'))
                    exchange(stock, key, 'export', outward, ident, dict(component=key, axis=axis, end=end, direction='export'))
                else:
                    add(key, other, outward, dict(component=key, axis=axis, end=end, direction='out'), physical_certificate_id=ident)
                    add(other, key, inward, dict(component=key, axis=axis, end=end, direction='in'), physical_certificate_id=ident)
            if wall_batches is not None:
                wall_batches.close_batch()
    finally:
        if wall_batches is not None:
            # End of the wall pass, also on an error: every wall worker is confirmed stopped here.
            wall_batches.close()

    # Moving fan separators need their actual relative speed. Material chart
    # boundaries (including earlier clipped boundaries) move with the material
    # and have zero relative flux. Current plate boundaries route only through
    # their original declared finite ridge/trench definitions.
    groups, boundary_exchanges = {}, []
    for key, (support, row, part) in components.items():
        omega = D._load_vec(row['material_angular_velocity_rad_s'])
        for name, sign in part['constraints']:
            constraint_owner = owned_constraint(row['constraints'][name])
            constraint = constraint_owner.value
            if D._material_plane(constraint, omega):
                continue
            identity = D._interface_identity(constraint)
            if identity is None:
                raise V.VolumeError('nonmaterial angular interface lacks exact retained plane authority')
            token = tuple(row['voxel_index']), row['source_chart_id'], identity[0]
            groups.setdefault(token, []).append((key, name, sign*identity[1]))
    if _observer is not None:
        _observer.mark('fixed-walls')
        # Its own instance of the lazy lookahead below: which contacts a session is offered.
        _observer.lookahead(components, boxes, _exterior_interface_jobs(components, groups, owned))
    if _parallel is not None:
        _parallel.prepare(_exterior_interface_jobs(components, groups, owned))
    # Scheduling only: the rolling batches of this pass read their own instances of that lookahead.
    interface_batches = S.open_interface_batches(
        _observer, _parallel, lambda: _exterior_interface_jobs(components, groups, owned))
    for (_, _, plane), entries in groups.items():
        handled = set()
        for key, name, sign in entries:
            support, row, _ = components[key]
            opposites = [(other, other_name) for other, other_name, s in entries if s == -sign]
            if opposites:
                if (key, name) in owned:
                    raise V.VolumeError('coincident finite boundary cannot be paired as an internal angular interface')
                for other, other_name in opposites:
                    token = tuple(sorted((key, other)))
                    if token in handled:
                        continue
                    handled.add(token)
                    if _observer is not None:
                        _observer.begin_interface()
                    begun = None if _observer is None else perf_counter()
                    ident, measured = interface(support, key, name,
                        other_support=components[other][0], other_logical_cell_id=other)
                    if _observer is not None:
                        _observer.interface(key, name, other, measured, perf_counter()-begun)
                    if ({(key, name), (other, other_name)} & represented and
                            any(_pair(measured, n)[1] for n in ('inward_volume_bounds_m3', 'outward_volume_bounds_m3'))):
                        raise second
                    add(key, other, _pair(measured, 'outward_volume_bounds_m3'), dict(moving=token, donor=key), physical_certificate_id=ident)
                    add(other, key, _pair(measured, 'inward_volume_bounds_m3'), dict(moving=token, donor=other), physical_certificate_id=ident)
                continue
            if _observer is not None:
                _observer.begin_interface()
            begun = None if _observer is None else perf_counter()
            ident, measured = interface(support, key, name)
            if _observer is not None:
                _observer.interface(key, name, None, measured, perf_counter()-begun)
            inward, outward = (_pair(measured, n) for n in ('inward_volume_bounds_m3', 'outward_volume_bounds_m3'))
            ownership = owned.get((key, name))
            if ownership is not None:
                resolved[key, name] = dict(ownership, physical_certificate_id=ident)
            if not inward[1] and not outward[1]:
                continue
            if (key, name) in represented:
                raise second
            found = {b['boundary_id']: b for b in boundaries.get(plane, ())
                     if row['plate_id'] in (b['left_plate_id'], b['right_plate_id'])}
            if len(found) != 1:
                raise V.VolumeError('positive relative moving flux lacks a unique actual plate boundary')
            boundary = next(iter(found.values()))
            if ownership is not None and boundary['boundary_id'] != ownership['boundary_id']:
                raise V.VolumeError('coincident fixed/angular boundary authority differs')
            side = 'left' if boundary['left_plate_id'] == row['plate_id'] else 'right'
            if inward[1]:
                candidates = [s for s in stocks.values() if s['lineage'].get('kind') == 'declared-finite-shell-birth' and
                    s['lineage'].get('supply') == boundary['supplies'].get(side) and
                    s['lineage'].get('source_id') == row['source_key'][0] and s['lineage'].get('sublayer') == row['source_key'][1]]
                if len(candidates) != 1 or row.get('finite_stock_id') != candidates[0]['stock_id']:
                    raise V.VolumeError('ridge relative inflow must enter its actual newly born finite-source component')
                boundary_exchanges.append((candidates[0], key, 'supply', inward, ident, boundary['boundary_id'], plane))
            if outward[1]:
                candidates = [s for s in stocks.values() if s['lineage'].get('kind') == 'declared-finite-trench-export' and
                    s['lineage'].get('sink') == boundary['sink'] and
                    s['lineage']['source_context'].get('plate_id') == row['plate_id']]
                if len(candidates) != 1 or W._decode(candidates[0]['lineage']['destination_fraction']) != 1:
                    raise V.VolumeError('multiple trench destinations require a shared proportional export variable, not independent interval choices')
                boundary_exchanges.append((candidates[0], key, 'export', outward, ident, boundary['boundary_id'], plane))
    if _observer is not None:
        _observer.mark('moving-interfaces')
    if interface_batches is not None:
        # End of the pass. An enclosure that leaves it early is closed by its caller instead.
        interface_batches.close()

    # A boundary path can turn inside one voxel, so one component may meet the
    # same finite boundary on several segments in the same direction. Each is
    # its own physical surface and stream. The original identity (boundary,
    # component, direction) is kept byte for byte wherever it names one
    # surface, as in every record issued so far: a second such surface gave the
    # same hash and its closure refused the duplicate. Only those surfaces add
    # their canonical segment, independent of ray order and of visiting order.
    shared = {}
    for _, key, direction, _, _, boundary_id, plane in boundary_exchanges:
        shared.setdefault((boundary_id, key, direction), []).append(plane)
    for stock, key, direction, bounds, ident, boundary_id, plane in boundary_exchanges:
        identity = dict(boundary=boundary_id, component=key, direction=direction)
        if len(shared[boundary_id, key, direction]) > 1:
            identity['segment'] = _segment_identity(plane)
        exchange(stock, key, direction, bounds, ident, identity)

    if set(resolved) != set(owned):
        raise V.VolumeError('coincident fixed face lacks its angular physical routing certificate')
    rows = [resolved[token] for token in sorted(resolved)]
    for row in rows:
        streams.keep(row)
    return rows


def enclose_differential_ale(partition, interval, funding, collar, source_flow_stage, *,
                            native_measures, native_projection, native_directed_volumes,
                            finite_stock_state, max_volume_error_m3, max_stream_error_m3,
                            max_leaves, budget, max_native_mask_leaves=None, _parallel=None,
                            parallel=None, _component_parallel=None, _endpoint_checkpoints=None):
    """Issue physical bounds BEFORE the finite-stock/GCL circulation.

    Error requests are per endpoint and per directed physical interface. They
    are retained separately, not summed into a more permissive velocity gate.
    Algebraic native ports carry the lower end of each certified
    positive/negative Q2 stream and share one counterflow bypass per face;
    component masks partition that family. Finite supplies/receivers remain
    actual inventory nodes in ``close_differential_ale``; this issuer never
    funds them.
    An explicit native-mask leaf ceiling applies only to corrected mechanical
    polynomial contact masks. None retains the common ceiling and record shape;
    endpoint volumes, rigid streams and moving interfaces keep max_leaves.
    ``parallel`` is an InterfaceParallelPolicy (None: its defaults) for the
    automatic choice of optional endpoint, exact-interface and fixed-wall workers. It
    selects execution only and cannot change the issued record. An explicit
    ``_parallel`` session is used as given, with no automatic selection and
    no observer.
    """
    automatic = observer = None
    try:
        _native_mask_leaf_limit(max_leaves, max_native_mask_leaves)
        if (type(partition) is not D.DifferentialPartition or type(interval) is not D.DifferentialInterval or
                type(funding) is not FullCellFunding or type(native_measures) is not N.NativeFaceMeasures or
                type(native_projection) is not P.NativeFluxProjection or type(native_directed_volumes) is not P.NativeDirectedVolumes or
                type(finite_stock_state) is not FiniteStockState or type(budget) is not WorkBudget or
                any(r is not budget for r in (partition._resource, interval._resource, funding._resource,
                    native_measures._resource, native_projection._resource, native_directed_volumes._resource,
                    finite_stock_state._owner._budget, collar._budget))):
            raise V.VolumeError('issued interval/partition/native measures/finite state on one shared budget required')
        if _parallel is None:
            # After the original validation, so its errors and their order are
            # unchanged. Never raises an Exception; either part may be None.
            automatic = S.open_automatic(budget=budget, max_width_m3=max_stream_error_m3,
                                         max_leaves=max_leaves, policy=parallel)
            _parallel, observer = automatic.session, automatic.observer
            if _component_parallel is None:
                _component_parallel = E.open_automatic_endpoints(automatic, max_volume_error_m3)
        with RoutingArena(budget) as arena:
            # Caller-owned issued bytes are not charged again. Their materialised
            # dictionary views and this operation's encoded output are temporary.
            size = sum(len(r._json) for r in (partition, interval, native_measures, native_projection, native_directed_volumes))
            arena.stack.enter_context(budget.reserve(131072+8*size, category='differential-ale-input-views'))
            return _enclose(partition, interval, funding, collar, source_flow_stage,
                native_measures=native_measures, native_projection=native_projection,
                native_directed_volumes=native_directed_volumes, finite_stock_state=finite_stock_state,
                max_volume_error_m3=max_volume_error_m3, max_stream_error_m3=max_stream_error_m3,
                max_leaves=max_leaves, budget=budget, arena=arena,
                max_native_mask_leaves=max_native_mask_leaves, _parallel=_parallel, _observer=observer,
                _component_parallel=_component_parallel,
                _endpoint_checkpoints=_endpoint_checkpoints)
    finally:
        try:
            if _component_parallel is not None:
                _component_parallel.close()
        finally:
            try:
                if _parallel is not None:
                    # An unconfirmed worker shutdown still propagates from here.
                    _parallel.close()
            finally:
                try:
                    if automatic is not None:
                        # Rolling batch workers of a pass that ended early; the same propagation.
                        automatic.close()
                finally:
                    if automatic is not None:
                        # Folds observations and records the decision; never raises an Exception.
                        automatic.finish()


def _enclose(partition, interval, funding, collar, source_flow_stage, *, native_measures,
             native_projection, native_directed_volumes, finite_stock_state,
             max_volume_error_m3, max_stream_error_m3, max_leaves, budget, arena,
              max_native_mask_leaves=None, _parallel=None, _observer=None, _component_parallel=None,
              _endpoint_checkpoints=None):
    native_mask_leaves = _native_mask_leaf_limit(max_leaves, max_native_mask_leaves)
    native_measures.validate_source(collar, source_flow_stage)
    native_projection.validate_source(native_measures, funding)
    native_directed_volumes.validate_source(native_measures, native_projection)
    finite_stock_state._owner._verify()
    width, stream_width = W._q(max_volume_error_m3), W._q(max_stream_error_m3)
    if min(width, stream_width) < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('explicit nonnegative physical error widths and finite leaf ceiling required')
    if getattr(partition, '_compact', None) is None:
        p, step, original = partition.record(), interval.record(), funding.descriptor()
    else:
        # Only the fields read below, owned while borrowed; original call order.
        from partition_native_patch import partition_fields as _partition_fields
        partition_owner = _partition_fields(partition, ('scope', 'interval_id', 'funding_id', 'collar_plan_id', 'source', 'component_keys', 'start_time_s', 'end_time_s', 'finite_owner_id', 'finite_state_id', 'grid_lines', 'grid_origin_m', 'grid_basis', 'native_contacts', 'parent_partition_id', 'start_support_id', 'end_support_id', 'trajectory', 'trajectory_id', 'prior_trajectory_id', 'grid_id', 'support_ids', 'identity_start_cells'))
        p, step, original = partition_owner.value, interval.record(), funding.descriptor()
    native, directed = native_measures.record(), native_directed_volumes.record()
    stock_record = finite_stock_state.record()
    if (p.get('scope') != 'physical-interval' or p['interval_id'] != interval.interval_id or
            p['funding_id'] != funding.funding_id or p['collar_plan_id'] != collar.plan_id or
            p['source'] != original['source'] or p['component_keys'] != native['component_keys'] or
            p['start_time_s'] != native['start_time_s'] or p['end_time_s'] != native['end_time_s'] or
            p['finite_owner_id'] != finite_stock_state._owner.owner_id or
            p['finite_state_id'] != finite_stock_state.state_id or native['mechanics_scope'] != 'complete-grid'):
        raise V.VolumeError('actual differential source, finite parent, registry, native stage or clocks differ')
    stocks = {r['stock_id']: r for r in stock_record['stocks']}
    cells, receipts = {}, {}
    def keep(row):
        arena.stack.enter_context(budget.reserve(128+_width(row), category='differential-ale-output-views'))
    support_rows = SupportRoutingRows(partition.supports, budget, arena)
    components, component_keys = {}, {}
    native_boxes = collar.cell_geometries()
    native_ids = {}
    for flat, box in enumerate(native_boxes):
        key = W._hash(dict(kind='collar', funding_id=funding.funding_id, cell_id=box.cell_id))
        native_ids[flat] = key
        cells[key] = dict(cell_id=key, kind='collar', index=flat, physical_cell_id=box.cell_id,
            start_volume_bounds_m3=[D._qtext(box.volume_m3)]*2,
            end_volume_bounds_m3=[D._qtext(box.volume_m3)]*2)
        keep(cells[key])

    def retain(measure):
        row = support_rows.measure_record(measure)
        if not row['met']:
            # Complete replay inputs use prepaid failure capacity. Their leases
            # remain live with the error/traceback until the writer is finished.
            keep(row)
            raise _unmet_measure_error(row, support_rows, budget)
        # Retain the numerical evidence once; component/face rows refer to it.
        ident = measure.measure_id
        if ident not in receipts:
            keep(row)
            receipts[ident] = row
        return ident, row

    streams = _Streams(cells, support_rows, receipts, keep)
    add, exchange, faces, exchanges = streams.add, streams.exchange, streams.faces, streams.exchanges

    # Endpoint volumes are physical, not the thermal surrogate. Identity
    # siblings/births have exactly zero true start support by the issued chart
    # partition, while every carried positive parent keeps its own field.
    if _component_parallel is not None:
        _component_parallel.prepare(partition.supports)
    for support in partition.supports:
        row = support_rows.project(support)
        E.bind_support(_component_parallel, support, row)
        with ComponentVolumeQueries(support, budget=budget) as volumes:
            for part in row['components']:
                key = part['logical_cell_id']
                endpoints = {}
                witness = {}
                for endpoint in ('start', 'end'):
                    if endpoint == 'start' and part['parent_cell_id'] is None:
                        endpoints[endpoint] = [D._qtext(Q(0))]*2
                        continue
                    ident, measured = retain(E.measure_endpoint(volumes, _component_parallel, key, endpoint=endpoint,
                        max_width_m3=width, max_leaves=max_leaves, positive_witness=True, _funded=(None if _component_parallel is None
                            else _component_parallel.claim),
                        _checkpoint=_endpoint_checkpoints))
                    endpoints[endpoint] = [measured['lower_m3'], measured['upper_m3']]
                    if endpoint == 'end':
                        witness = {k: measured[k] for k in ('positive_witness_m3', 'positive_witness_point_m',
                                   'positive_witness_point_rule') if k in measured}
                cells[key] = dict(cell_id=key, kind='exterior', source_key=row['source_key'],
                    support_id=support.support_id, source_chart_id=row['source_chart_id'],
                    voxel_index=row['voxel_index'], radial_band=row['radial_band'], chart=row['chart'],
                    parent_cell_id=part['parent_cell_id'], start_volume_bounds_m3=endpoints['start'],
                    end_volume_bounds_m3=endpoints['end'], **witness)
                keep(cells[key])
                components[key] = support_rows._handles[support.support_id], row, part
                shape_key = row['source_chart_id'], tuple(part['partition_path'])
                component_keys[tuple(row['voxel_index']), shape_key] = key
    if _component_parallel is not None:
        _component_parallel.close()
    if _observer is not None:
        _observer.mark('endpoint-volumes')

    lines = tuple(tuple(map(W._decode, a)) for a in p['grid_lines'])
    origin, basis = D._load_vec(p['grid_origin_m']), tuple(map(D._load_vec, p['grid_basis']))
    boxes = {at: V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)),
        tuple(lines[j][at[j]+1] for j in range(3)), origin, basis, budget=budget)
        for at in product(*(range(len(a)-1) for a in lines))}
    arena.keep(tuple(q for box in boxes.values() for q in (*box.lower_m, *box.upper_m)), objects=len(boxes))
    native_at = {at: next((i for i, box in enumerate(native_boxes) if _inside(voxel, box)), None)
                 for at, voxel in boxes.items()}
    basal = [(r, V.CartesianCell.from_record(r['lineage']['physical_cell'], budget=budget)) for r in stocks.values()
             if r['lineage'].get('kind') == 'finite-basal-reservoir']
    excluded_at = {}
    for at, voxel in boxes.items():
        found = [stock for stock, box in basal if _inside(voxel, box)]
        if len(found) > 1:
            raise V.VolumeError('finite basal compartments overlap')
        if found:
            excluded_at[at] = found[0]
    originals = {r['face_id']: r for r in native['faces']}
    selected = {r['face_id']: r for r in directed['faces']}
    boundary_faces = {}
    ports = {}
    port = lambda flat, axis, end, inward: _native_port(ports, streams, selected, boundary_faces, native_ids,
        native_directed_volumes.directed_id, flat, axis, end, inward)

    for face in native['faces']:
        row = selected[face['face_id']]
        positive, negative = (W._decode(row[k]) for k in ('positive_volume_m3', 'negative_volume_m3'))
        lower, upper = face['lower'], face['upper']
        if lower is not None and upper is not None:
            add(native_ids[lower], native_ids[upper], (positive, positive), dict(native=face['face_id'], sign=1))
            add(native_ids[upper], native_ids[lower], (negative, negative), dict(native=face['face_id'], sign=-1))
        else:
            end, flat = (0, upper) if lower is None else (1, lower)
            boundary_faces[flat, face['axis'], end] = face
    contacts = {(r['native_index'], r['axis'], r['end']): r for r in p['native_contacts']}
    if set(contacts) != set(boundary_faces):
        raise V.VolumeError('issued physical partition does not cover every actual native boundary face')
    # Full basal faces connect to their actually carved compartment. Exterior
    # faces use the SAME actual Q2 polynomial, in the exact neighbour chart.
    for face_key, group in contacts.items():
        flat, axis, end = face_key
        face = boundary_faces[face_key]
        if group['excluded_subfaces']:
            chosen_stocks = {excluded_at[tuple(r['voxel_index'])]['stock_id'] for r in group['excluded_subfaces']}
            if group['contacts'] or len(chosen_stocks) != 1:
                raise V.VolumeError('a split basal/native face needs its explicit compartment-mask polynomial integral')
            stock = stocks[next(iter(chosen_stocks))]
            row = selected[face['face_id']]
            plus, minus = (W._decode(row[k]) for k in ('positive_volume_m3', 'negative_volume_m3'))
            inward, outward = (plus, minus) if end == 0 else (minus, plus)
            exchange(stock, native_ids[flat], 'supply', (inward, inward), native_directed_volumes.directed_id,
                     dict(native=face['face_id'], stock=stock['stock_id'], direction='supply'))
            exchange(stock, native_ids[flat], 'export', (outward, outward), native_directed_volumes.directed_id,
                     dict(native=face['face_id'], stock=stock['stock_id'], direction='export'))
            continue
        for contact in group['contacts']:
            key = contact['logical_cell_id']; support, row, _ = components[key]
            voxel = boxes[tuple(row['voxel_index'])]
            polynomial = N.component_normal_polynomial(native_measures, face['face_id'], voxel,
                contact['axis'], contact['end'], projection=native_projection, budget=budget)
            ident, measured = retain(_compact_wall(support, key, axis, contact['end'],
                normal_polynomial=polynomial.polynomial, max_width_m3=stream_width,
                max_leaves=native_mask_leaves, budget=budget))
            receipts[polynomial.polynomial_id] = polynomial.record()
            keep(receipts[polynomial.polynomial_id])
            add(key, port(flat, axis, end, True), _pair(measured, 'outward_volume_bounds_m3'),
                dict(contact=key, native=face['face_id'], inward=True), physical_certificate_id=ident)
            add(port(flat, axis, end, False), key, _pair(measured, 'inward_volume_bounds_m3'),
                dict(contact=key, native=face['face_id'], inward=False), physical_certificate_id=ident)
    if _observer is not None:
        _observer.mark('native-contacts')

    ownership = _route_exterior_surfaces(components, component_keys, boxes, native_at, excluded_at,
        _physical_boundary_index(step), stocks, streams,
        wall=lambda support, key, axis, end: retain(_compact_wall(support, key, axis, end,
            max_width_m3=stream_width, max_leaves=max_leaves, budget=budget,
            _funded=getattr(getattr(_observer, 'wall_batches', None), 'claim', None))),
        interface=lambda support, key, name, **pair: retain(_compact_interface(support, key, name,
            max_width_m3=stream_width, max_leaves=max_leaves, budget=budget,
            _funded=_parallel.claim if _parallel is not None and not getattr(_parallel, 'closed', False)
            else getattr(getattr(_observer, 'interface_batches', None), 'claim', None), **pair)),
        _parallel=_parallel, _observer=_observer)

    result = dict(schema='atlas.source-bound-spatial-ale-bounds.v1',
        physical_geometry_family='differential-plate-component-partition-v1',
        funding_id=funding.funding_id, source=p['source'], collar_plan_id=collar.plan_id,
        parent_state_id=source_flow_stage.parent_state_id, source_flow_stage_id=source_flow_stage.result_id,
        flow_id=source_flow_stage.flow.flow_id, native_measure_id=native_measures.measure_id,
        native_projection_id=native_projection.projection_id, native_directed_id=native_directed_volumes.directed_id,
        native_flux_projection=native_projection.record(), native_directed_volumes=native_directed_volumes.record(),
        interval_id=interval.interval_id, partition_id=partition.partition_id,
        finite_state_id=finite_stock_state.state_id, finite_owner_id=finite_stock_state._owner.owner_id,
        component_registry_id=finite_stock_state._owner.definition()['registry_id'],
        **{k: p[k] for k in ('parent_partition_id', 'component_keys', 'start_time_s', 'end_time_s',
            'start_support_id', 'end_support_id', 'trajectory', 'trajectory_id', 'prior_trajectory_id',
            'grid_id', 'grid_lines', 'grid_origin_m', 'grid_basis', 'support_ids', 'identity_start_cells')},
        cells=sorted(cells.values(), key=lambda r: r['cell_id']), face_intervals=sorted(faces, key=lambda r: r['face_id']),
        finite_exchange_intervals=sorted(exchanges, key=lambda r: r['face_id']), physical_measure_receipts=receipts,
        coincident_fixed_face_ownership=ownership,
        max_volume_error_m3=D._qtext(width), max_stream_error_m3=D._qtext(stream_width), max_leaves=max_leaves,
        physical_outer_boundary='actual finite ridge/trench/basal exchanges; no implicit refill or volume repair',
        coverage='issued complete carried component partition; relative angular and actual fixed Cartesian wall measures; '
                 'a fixed wall that is a stationary finite plate boundary is its angular face, measured once',
        zero_relative_interfaces='true radial spheres and material-transported chart planes, never thermal facets')
    if max_native_mask_leaves is not None:
        result['max_native_mask_leaves'] = max_native_mask_leaves
    return A._issue(A.SpatialALEBounds, result, budget)

from partition_routing_patch import owned_constraint, wall as _compact_wall, interface as _compact_interface
