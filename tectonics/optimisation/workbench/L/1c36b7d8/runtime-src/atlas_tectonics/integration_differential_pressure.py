"""Current differential material pressure and explicit reservoir boundary load.

The finite compartments are outside the force domain. An authored affine
pressure is imposed on EVERY exposed cut face, including the native base.
It is a boundary condition, not an inferred shape of depleted material. Its
work is external mechanical work, never silently converted to dissipative heat.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
import weakref

import numpy as np

from . import integration_differential_geometry as G
from . import integration_spatial_pressure as P
from . import integration_pressure_coupling as C
from . import integration_volume as V, integration_volume_overlap as O
from . import integration_wall_measures as W
from .regional_execution import RegionalMechanicalSnapshot
from .resources import WorkBudget


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _exact(value):
    if type(value) not in (Q, int):
        raise C.PressureCouplingRefused('an explicit exact rational pressure/geometry error is required')
    return Q(value)


def _issue(cls, metadata, arrays, budget):
    snapshot = RegionalMechanicalSnapshot(metadata, arrays)
    lease = budget.reserve(8192+2*snapshot.nbytes, category='differential-pressure-retained')
    lease.__enter__()
    try:
        result = object.__new__(cls)
        object.__setattr__(result, '_snapshot', snapshot)
        object.__setattr__(result, '_resource', budget)
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialPressureForcing:
    _snapshot: object = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialPressureForcing is issued from actual current material')

    @property
    def forcing_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(forcing_id=self.forcing_id, **self._snapshot.descriptor())

    def array(self, name):
        return self._snapshot.array(name)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ReservoirPressure:
    _snapshot: object = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('ReservoirPressure is issued by prescribe_reservoir_pressure')

    @property
    def closure_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(closure_id=self.closure_id, **self._snapshot.descriptor())

    def array(self, name):
        return self._snapshot.array(name)


def prescribe_reservoir_pressure(funding, collar, native, *, pressure_at_origin_pa,
                                gradient_pa_m, origin_world_m, source, budget):
    """Full physical p(x)=p0+gradient.(x-origin), on the entire carved union.

    The caller must supply the pressure model/source. No planetary constant,
    hydrostatic calibration, or pressure of remaining well-mixed stock is
    inferred. The same law generates the natural native traction and the
    exterior cut load. Native hydrostatic/reference subtraction happens later.
    """
    from .integration_collar_geometry import FullCellFunding
    from .regional_collar3d import PreparedRegionalCollar3D
    from .regional_execution3d import PreparedRegionalStokes3D
    if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
            type(native) is not PreparedRegionalStokes3D or type(budget) is not WorkBudget or
            funding._resource is not budget or collar._budget is not budget or native._resource is not budget):
        raise C.PressureCouplingRefused('actual funding, complete grid, native force plan and shared budget required')
    p0 = _exact(pressure_at_origin_pa)
    origin, gradient = tuple(map(_exact, origin_world_m)), tuple(map(_exact, gradient_pa_m))
    if len(origin) != 3 or len(gradient) != 3 or type(source) is not str or not source:
        raise C.PressureCouplingRefused('explicit world pressure origin, gradient and source required')
    f, plan, force_plan = funding.descriptor(), collar.descriptor(), native.descriptor()
    inventory = f.get('basal_inventory')
    if (plan.get('mechanics_scope') != 'complete-grid' or inventory is None or
            f['collar_plan_id'] != collar.plan_id or tuple(force_plan['cells']) != collar.cells or
            tuple(force_plan['lengths_m']) != collar._native.lengths_m or native._pattern != collar._native._pattern or
            collar._native._radial_constitutive is None):
        raise C.PressureCouplingRefused('pressure closure requires the actual funded open-base mechanical geometry')
    side = inventory['side']
    axis, end = 'xyz'.index(side[0]), int(side[1])
    if native._pattern[side] != ('traction',)*3:
        raise C.PressureCouplingRefused('the finite reservoir requires full natural traction on its native face')
    boxes = tuple(V.CartesianCell.from_record(r, budget=budget) for r in f['excluded_static_cells'])
    # One continuous pressure law across neighbouring inventory cells prevents
    # an unrepresented internal pressure jump between boundary compartments.
    for box in boxes:
        if any(p0+O._dot(gradient, tuple(x-o for x, o in zip(v, origin))) < 0 for v in box.vertices_m):
            raise C.PressureCouplingRefused('declared absolute reservoir pressure becomes negative on its support')
    local = native.coordinates(side)
    chart = V.CartesianCell.from_record(f['cell_geometries'][0], budget=budget)
    with budget.reserve(65536+4*local.nbytes+8*len(_json(f)), category='reservoir-full-traction'):
        # Exact affine pullback in the ACTUAL physical chart, at the native
        # solver's represented quadrature coordinates. Rounding a world point
        # first would hide an additional pressure/work projection residual.
        exact = [p0+O._dot(gradient, tuple(chart.origin_m[i]-origin[i]+
            sum(chart.basis[i][j]*Q(float(point[j])) for j in range(3)) for i in range(3)))
                 for point in local.reshape(-1, 3)]
        values = np.asarray(list(map(float, exact))).reshape(local.shape[:-1])
        if not np.isfinite(values).all():
            raise C.PressureCouplingRefused('reservoir traction is not representable in binary64')
        traction = np.zeros_like(local)
        traction[..., axis] = (1 if end == 0 else -1)*values
        residual = [V._encoded(Q(float(v))-q) for v, q in zip(values.flat, exact)]
        record = dict(schema='atlas.prescribed-reservoir-pressure.v1', funding_id=funding.funding_id,
            collar_plan_id=collar.plan_id, native_plan_id=native.plan_id, volume_map_id=plan['volume_map_id'],
            source=source, side=side, pressure_at_origin_pa=V._encoded(p0),
            gradient_pa_m=list(map(V._encoded, gradient)), origin_world_m=list(map(V._encoded, origin)),
            excluded_cells=f['excluded_static_cells'], exact_native_pressure_pa=list(map(V._encoded, exact)),
            native_pressure_projection_residual_pa=residual,
            quadrature_coordinates='represented native local coordinates mapped by the exact funded physical chart',
            convention='full physical traction sigma.n=-p(x)n; native subtracts its own reference exactly once',
            scope='finite boundary compartments outside force domain; explicit imposed pressure, not depletion geometry',
            work='all pressure-cut work is external mechanical work, not dissipative heating')
        return _issue(ReservoirPressure, record, dict(reservoir_native_traction_pa=traction), budget)


def _cut_faces(boxes, native_box, budget):
    """Exact exposed rectangles of the carved union, excluding native contacts."""
    obstacles = (*boxes, native_box)
    for box in boxes:
        if any(other.origin_m != box.origin_m or other.basis != box.basis for other in obstacles):
            raise C.PressureCouplingRefused('cut union requires its actual shared orthogonal grid chart')
        for axis in range(3):
            tangents = tuple(j for j in range(3) if j != axis)
            for end in (0, 1):
                at = (box.lower_m, box.upper_m)[end][axis]
                neighbours = [other for other in obstacles if other.cell_id != box.cell_id and
                    ((other.lower_m[axis] < at <= other.upper_m[axis]) if end == 0 else
                     (other.lower_m[axis] <= at < other.upper_m[axis]))]
                lines = [sorted({box.lower_m[j], box.upper_m[j], *(q for other in neighbours
                    for q in (other.lower_m[j], other.upper_m[j]) if box.lower_m[j] < q < box.upper_m[j])})
                    for j in tangents]
                for u0, u1 in zip(lines[0], lines[0][1:]):
                    for v0, v1 in zip(lines[1], lines[1][1:]):
                        midpoint = ((u0+u1)/2, (v0+v1)/2)
                        if any(all(other.lower_m[j] < q < other.upper_m[j] for j, q in zip(tangents, midpoint))
                               for other in neighbours):
                            continue
                        lo, hi = list(box.lower_m), list(box.upper_m)
                        for j, a, b in zip(tangents, (u0, v0), (u1, v1)):
                            lo[j], hi[j] = a, b
                        yield V.CartesianCell(tuple(lo), tuple(hi), box.origin_m, box.basis, budget=budget), axis, end


def _pressure_torque_polynomials(face, pressure):
    """Torque of +p*n_reservoir on the adjacent active material, exactly."""
    origin, eu, ev, normal, _ = face
    p0 = W._decode(pressure['pressure_at_origin_pa'])
    gradient = tuple(map(W._decode, pressure['gradient_pa_m']))
    anchor = tuple(map(W._decode, pressure['origin_world_m']))
    affine = {(0, 0): p0+O._dot(gradient, tuple(a-b for a, b in zip(origin, anchor))),
              (1, 0): O._dot(gradient, eu), (0, 1): O._dot(gradient, ev)}
    crosses = {power: O._cross(vector, normal) for power, vector in
               (((0, 0), origin), ((1, 0), eu), ((0, 1), ev))}
    result = []
    for j in range(3):
        terms = {}
        for (a, b), coefficient in affine.items():
            for (c, d), cross in crosses.items():
                power = a+c, b+d
                terms[power] = terms.get(power, Q(0))+coefficient*cross[j]
        result.append(tuple((i, k, q) for (i, k), q in sorted(terms.items()) if q))
    return tuple(result)


def _cut_torque(geometry, endpoint, pressure, native_box, radius, support_radius,
                plates, width, max_leaves, budget):
    boxes = tuple(V.CartesianCell.from_record(r, budget=budget) for r in pressure['excluded_cells'])
    faces = tuple(_cut_faces(boxes, native_box, budget))
    layer = V.RadialLayer(radius, 0, radius-support_radius, budget=budget)
    limit = width/max(1, len(faces)*len(plates))
    result = [[(Q(0), Q(0)) for _ in range(3)] for _ in plates]
    records = []
    for cell, axis, end in faces:
        polynomials = _pressure_torque_polynomials(W._face(cell, axis, end), pressure)
        for j, plate in enumerate(plates):
            args = dict(moment_polynomials=polynomials, max_moment_widths=(limit,)*3,
                        max_leaves=max_leaves, budget=budget)
            query = (G.enclose_current_face(geometry, plate, layer, cell, axis, end, **args)
                     if type(geometry) is G.CurrentGeometry else
                     G.enclose_differential_face_at(geometry, plate, layer, cell, axis, end, endpoint=endpoint, **args))
            record = query.record()
            if not record['met']:
                raise C.PressureCouplingRefused('reservoir cut traction exceeds the declared torque integration budget')
            bounds = [tuple(map(W._decode, row)) for row in record['moment_bounds']]
            result[j] = [C._add(a, b) for a, b in zip(result[j], bounds)]
            records.append(dict(cell_id=cell.cell_id, axis=axis, end=end, plate_id=plate,
                certificate_id=query.measure_id, bounds_n_m=record['moment_bounds']))
    return result, records


class _KernelPose:
    """Internal view of an already validated boundary pose; no issuing power.

    history is the pose record's exact (angular velocity, duration) steps. The
    view keeps every step's exact vector in _history and its duration in
    _plane_history: a statement about the
    TRUE pose of the same standing as _error. If every nonzero step vector is
    exactly parallel to one vector k, the true pose is a rotation about k, and
    if the rational representative and its transpose also fix k exactly, the
    two give every point the same coordinate along k. The wall kernel proves
    that from _history on each of its calls (P._pose_axis); _axis is the same
    proof for inspection and is never stored.
    """
    def __init__(self, rotation, error, *, history=None):
        self._rotation, self._error = rotation, error
        self._plane_history = (None if history is None else
            tuple((tuple(map(Q, vector)), Q(duration)) for vector, duration in history))
        self._history = tuple(vector for vector, _ in self._plane_history or ())

    @property
    def _axis(self):
        return P._common_axis(self._rotation, self._history)

    def rotation(self):
        return self._rotation


def _boundary_views(network, geometry, endpoint, operator_error, budget):
    if type(geometry) is G.DifferentialInterval or geometry.record().get('accepted_interval_id'):
        for boundary in network.boundaries:
            issued = G.posed_boundary(geometry, boundary.boundary_id, endpoint=endpoint,
                max_operator_error=operator_error, budget=budget)
            record = issued.record()
            history = tuple((tuple(map(W._decode, step['angular_velocity_rad_s'])),
                             W._decode(step['end_time_s'])-W._decode(step['start_time_s']))
                            for step in record['boundary_rotations'])
            pose = _KernelPose(tuple(tuple(map(W._decode, row)) for row in record['rotation_matrix']),
                               W._decode(record['pose_operator_error_bound']), history=history)
            for segment in record['segments']:
                rays = tuple(tuple(map(W._decode, row)) for row in segment['original_rays'])
                yield boundary.left_plate_id, boundary.right_plate_id, rays, pose, issued.pose_id
    else:
        # Only a fresh instantaneous source is allowed here. Continued current
        # geometry needs the retained boundary history, never a rounded reset.
        record = geometry.record()
        if any(row.get('prior_rotations') for row in record['rays'].values()):
            raise C.PressureCouplingRefused('continued force geometry requires its retained boundary pose')
        identity = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
        for boundary in network.boundaries:
            chain = list(boundary.vertex_ids)
            if boundary.closed:
                chain += chain[:1]
            for first, second in zip(chain, chain[1:]):
                rays = tuple(tuple(map(W._decode, record['rays']['vertex:'+name]['direction']))
                             for name in (first, second))
                yield boundary.left_plate_id, boundary.right_plate_id, rays, _KernelPose(identity, Q(0)), geometry.geometry_id


def _current_regions(sphere, funding, collar, state, spatial_state, supports, endpoint,
                     radius, support_radius, budget):
    from . import integration_exterior_mesh as E, integration_support as U
    f, current = funding.descriptor(), spatial_state.record()
    fields = collar._fields(state)
    cells = collar.cell_geometries()
    material = collar._native._material
    count = len(collar._native._composition)
    masses = fields['component_mass_kg'].reshape(count, -1)
    regions, densities = [], []
    for i, (cell, energy) in enumerate(zip(cells, fields['enthalpy_j'].flat)):
        low, high = cell.radial_bounds_squared_m2
        if low < support_radius**2 or high > radius**2:
            raise C.PressureCouplingRefused('native material outside the declared pressure support')
        rho, temperature = P._density(material, Q(float(energy)), tuple(Q(float(v)) for v in masses[:, i]), budget)
        regions.append(dict(cell=cell, cone=(), radial=(support_radius, radius), density=rho, plate_id=None))
        densities.append(dict(cell_id=cell.cell_id, density_kg_m3=V._encoded(rho), temperature_k=V._encoded(temperature)))
    mesh = current['thermal_mesh']
    thermal = {r['logical_cell_id']: r for r in mesh['cells'] if r['kind'] == 'exterior'}
    if len(thermal) != len(current['cells']) or set(thermal) != {r['cell_id'] for r in current['cells']}:
        raise C.PressureCouplingRefused('carried fields and physical support have different cell coverage')
    posed = {}
    for support in supports:
        if type(support) is not G.DifferentialSupport or support._resource is not budget:
            raise C.PressureCouplingRefused('issued current physical component supports required')
        view = G.posed_support(support, endpoint=endpoint, budget=budget).record()
        if view['support_id'] in posed:
            raise C.PressureCouplingRefused('duplicate physical support')
        posed[view['support_id']] = support.record(), view
    patch_faces = {p.patch_id: p.face_id for p in U.required(sphere.material).patches}
    face_plates = {face.face_id: face.plate_id for face in sphere.network.faces}
    for row in current['cells']:
        mesh_row = thermal[row['cell_id']]
        if row['source_key'] != mesh_row['source_key']:
            raise C.PressureCouplingRefused('carried cell lineage differs from its physical support')
        physical = E.resolve_physical_support(mesh, mesh_row)
        extra, cone, physical_planes = (), (), ()
        if 'support' in physical:
            raw = physical['support']
            support_id = hashlib.sha256(_json(raw)).hexdigest()
            if support_id not in posed or posed[support_id][0] != raw:
                raise C.PressureCouplingRefused('force supplied a different physical component geometry')
            raw_support, view = posed[support_id]
            if W._decode(view['time_s']) != Q(current['time_s']):
                raise C.PressureCouplingRefused('component force geometry has another clock')
            component = physical['component']
            planes, physical_planes = [], []
            elapsed = Q(0) if endpoint == 'start' else W._decode(raw_support['duration_s'])
            for name, sign in component['constraints']:
                plane = view['constraints'][name]
                normal = tuple(-sign*W._decode(v) for v in plane['normal'])
                planes.append((*normal, -sign*W._decode(plane['offset']), W._decode(plane['error_euclidean'])))
                # Borrow the exact issuer record in the SAME literal order.
                # It is a premise to prove on each wall, never a stored verdict.
                physical_planes.append((view['physical_constraint_record'][name], elapsed))
            extra, plate, geometry = tuple(planes), view['plate_id'], view
        else:
            if current['intervals'] or current['time_s'] != f['time_s']:
                raise C.PressureCouplingRefused('old source cones cannot locate an advanced differential field')
            geometry = physical
            cone = tuple(tuple(map(W._decode, p)) for p in physical['original_cone'])
            plate = face_plates[patch_faces[row['source_key'][0]]]
        layer = geometry['radial_layer']
        if W._decode(layer['radius_m']) != radius or layer['convention'] != V.PHYSICAL_RADIAL_SHELL:
            raise C.PressureCouplingRefused('pressure uses another radial geometry convention')
        rb, rt = radius-W._decode(layer['bottom_depth_m']), radius-W._decode(layer['top_depth_m'])
        if not support_radius <= rb < rt <= radius:
            raise C.PressureCouplingRefused('current material band outside declared pressure support')
        exact = row['exact']
        rho, temperature = P._density(material, W._decode(exact['enthalpy_j']),
            tuple(W._decode(exact['component_mass_kg:'+str(i)]) for i in range(count)), budget)
        regions.append(dict(cell=V.CartesianCell.from_record(geometry['voxel'], budget=budget),
            cone=cone, world_planes=extra, _physical_planes=tuple(physical_planes),
            radial=(rb, rt), density=rho, plate_id=plate))
        densities.append(dict(cell_id=row['cell_id'], density_kg_m3=V._encoded(rho), temperature_k=V._encoded(temperature)))
    return regions, densities, cells


def differential_pressure_forcing(sphere, network, geometry, funding, collar, state, spatial_state,
                                  native, datum, reservoir_pressure, *, supports=(), endpoint='end',
                                  source_moving, exterior_parent_state_id, max_torque_width_n_m,
                                  max_operator_error, max_leaves, budget):
    """Current physical pressure partition, without an archived P1/D1 field.

    A spherically uniform mantle support and surface load have exactly zero
    net torque on each closed spherical plate. Actual material replaces that
    reference only on its physical support. This retains the RadialDatum's
    prescribed hydrostatic support, without creating mantle inventory.
    """
    from .integration_collar_geometry import FullCellFunding
    from .integration_spatial_owner import SpatialExteriorState
    from .integration_radial_pressure import RadialDatum
    from . import integration_material as M, integration_support as U
    from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarState
    from .regional_execution3d import PreparedRegionalStokes3D
    if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
            type(state) is not RegionalCollarState or type(spatial_state) is not SpatialExteriorState or
            type(geometry) not in (G.CurrentGeometry, G.DifferentialInterval) or
            type(native) is not PreparedRegionalStokes3D or type(datum) is not RadialDatum or
            type(reservoir_pressure) is not ReservoirPressure or type(budget) is not WorkBudget or
            any(v is not budget for v in (funding._resource, collar._budget, spatial_state._budget,
                geometry._resource, native._resource, reservoir_pressure._resource))):
        raise C.PressureCouplingRefused('actual current material/geometry, force plan, datum and reservoir closure required')
    width, operator_error = _exact(max_torque_width_n_m), _exact(max_operator_error)
    if width <= 0 or not 0 < operator_error < 1 or type(max_leaves) is not int or max_leaves < 1:
        raise C.PressureCouplingRefused('explicit positive torque/operator budgets and bounded leaves required')
    if type(exterior_parent_state_id) is not str or not exterior_parent_state_id:
        raise C.PressureCouplingRefused('actual nonpressure exterior force parent required')
    f, c, geo, pressure = funding.descriptor(), spatial_state.record(), geometry.record(), reservoir_pressure.descriptor()
    M.bound_moving(source_moving, sphere)
    if source_moving.moving_id != f['source']['moving_id']:
        raise C.PressureCouplingRefused('current force coverage needs the actual original source-layer inventory')
    expected = {(patch.patch_id, j) for patch in U.required(sphere.material).patches
                for j in range(len(source_moving.cohort(patch.cohort_id).sublayers))}
    actual = set(map(tuple, f['component_keys']))
    if actual != expected:
        raise C.PressureCouplingRefused('global current pressure requires all real source layers; unfunded material is not mantle')
    time = state.native_state.descriptor()['time_s']
    geometry_id = geometry.geometry_id if type(geometry) is G.CurrentGeometry else geometry.interval_id
    if type(geometry) is G.CurrentGeometry:
        current_network, geometry_time = geo['network_id'], W._decode(geo['time_s'])
        if geo.get('accepted_interval_id') and (geo['accepted_support_id'] != c['support_id'] or
                                               geo['accepted_trajectory_id'] != c['trajectory_id']):
            raise C.PressureCouplingRefused('retained current pressure geometry differs from carried material')
    else:
        if endpoint not in ('start', 'end'):
            raise C.PressureCouplingRefused('explicit current pressure endpoint required')
        current_network = geo['parent_network_id' if endpoint == 'start' else 'endpoint_network_id']
        geometry_time = W._decode(geo[endpoint+'_time_s'])
        if geo[endpoint+'_support_id'] != c['support_id']:
            raise C.PressureCouplingRefused('physical pressure support is not the carried support')
    if (current_network != network.network_id or geometry_time != Q(time) or c['time_s'] != time or
            c['funding_id'] != funding.funding_id or f['source']['sphere_state_id'] != sphere.state_id or
            f['collar_plan_id'] != collar.plan_id or pressure['collar_plan_id'] != collar.plan_id or
            pressure['funding_id'] != funding.funding_id or pressure['native_plan_id'] != native.plan_id or
            pressure['volume_map_id'] != f['volume_map_id'] or
            (c['intervals'] and c['collar_state_id'] != state.result_id) or
            (not c['intervals'] and state.native_state.result_id != f['native_initial_state_id'])):
        raise C.PressureCouplingRefused('stale material/force/geometry/pressure source or clock')
    mesh = c['thermal_mesh']
    if (mesh['funding_id'] != funding.funding_id or mesh['source'] != f['source'] or
            mesh['support_id'] != c['support_id'] or mesh['trajectory_id'] != c['trajectory_id'] or
            W._decode(mesh['time_s']) != Q(time) or mesh['grid_id'] != c['grid_id']):
        raise C.PressureCouplingRefused('carried pressure field has stale physical-support provenance')
    material = collar._native._material
    if material.reference_temperature_k != datum.reference_temperature_k or material.composition_density_contrast_kg_m3 != 0:
        raise C.PressureCouplingRefused('matching explicit thermal EOS with no undeclared composition density required')
    rc, radius = Q(datum.support_radius_m), Q(datum.reference_radius_m)
    if radius != Q(network.sphere.radius_m):
        raise C.PressureCouplingRefused('pressure datum and physical sphere differ')
    size = 262144+6*spatial_state._snapshot.nbytes+4*funding._snapshot.nbytes
    with budget.reserve(size, category='differential-current-pressure'):
        regions, densities, cells = _current_regions(sphere, funding, collar, state, spatial_state,
            supports, endpoint, radius, rc, budget)
        native_box = V.CartesianCell(tuple(min(c.lower_m[j] for c in cells) for j in range(3)),
            tuple(max(c.upper_m[j] for c in cells) for j in range(3)), cells[0].origin_m, cells[0].basis, budget=budget)
        reservoirs = tuple(V.CartesianCell.from_record(r, budget=budget) for r in pressure['excluded_cells'])
        walls = tuple(_boundary_views(network, geometry, endpoint, operator_error, budget))
        order = {p: i for i, p in enumerate(network.plate_ids)}
        zero = lambda: [[(Q(0), Q(0)) for _ in range(3)] for _ in order]
        full, owned, reservoir_removed = zero(), zero(), zero()
        profile = ((rc, radius, Q(datum.mantle_density_kg_m3), Q(datum.surface_pressure_pa)),)
        allowance = width/(8*max(1, len(walls)*(1+len(reservoirs))))
        certificates, leaves = [], 0
        for left, right, rays, pose, certificate in walls:
            selected = [dict(region, side=None if region['plate_id'] is None else (0 if region['plate_id'] == left else 1))
                        for region in regions if region['plate_id'] in (None, left, right)]
            args = dict(gravity=Q(datum.gravity_m_s2), support_radius=rc, radius=radius,
                        width=allowance, max_leaves=max_leaves, budget=budget)
            force, removed, used = P.moving_wall_integrals(*rays, (profile, profile), selected, native_box, pose, **args)
            leaves += used
            reservoir_wall = [(Q(0), Q(0)) for _ in range(3)]
            for box in reservoirs:
                _, cut, used = P.moving_wall_integrals(*rays, (profile, profile), selected, box, pose,
                                                     compute_density=False, **args)
                reservoir_wall = [C._add(a, b) for a, b in zip(reservoir_wall, cut)]
                leaves += used
            for plate, sign in ((left, 1), (right, -1)):
                for target, values in ((full, force), (owned, removed), (reservoir_removed, reservoir_wall)):
                    target[order[plate]] = [C._add(a, C._scale(b, sign)) for a, b in zip(target[order[plate]], values)]
            certificates.append(certificate)
        external, cut_records = _cut_torque(geometry, endpoint, pressure, native_box, radius, rc,
            network.plate_ids, width/8, max_leaves, budget)
        net_cut = [[(a[0]-b[1], a[1]-b[0]) for a, b in zip(aa, bb)] for aa, bb in zip(external, reservoir_removed)]
        arrays, exact = {}, {}
        errors = [[Q(0)]*3 for _ in order]
        entries = (('hydrostatic_wall_torque_n_m', full), ('native_owned_wall_torque_n_m', owned),
            ('reservoir_cut_torque_n_m', net_cut), ('reservoir_imposed_cut_torque_n_m', external),
            ('reservoir_removed_wall_torque_n_m', reservoir_removed))
        for name, bounds in entries:
            values = np.asarray([[float((a+b)/2) for a, b in row] for row in bounds])
            if not np.isfinite(values).all():
                raise C.PressureCouplingRefused('current differential pressure torque cannot be represented')
            arrays[name] = values
            exact[name] = [[list(map(V._encoded, pair)) for pair in row] for row in bounds]
            if name in {row[0] for row in entries[:3]}:
                for i, (vs, qs) in enumerate(zip(values, bounds)):
                    for j, (v, (a, b)) in enumerate(zip(vs, qs)):
                        errors[i][j] += (b-a)/2+abs(Q(float(v))-(a+b)/2)
        if any(q > width for row in errors for q in row):
            raise C.PressureCouplingRefused('current pressure and cut load exceed their declared torque error')
        # Sum enclosures and binary64 projection errors EXACTLY before one
        # outward conversion. A float sum plus one ulp need not enclose several
        # independently rounded contributions.
        error_values = np.asarray([[float(q) for q in row] for row in errors])
        for i, row in enumerate(errors):
            for j, q in enumerate(row):
                if Q(float(error_values[i, j])) < q:
                    error_values[i, j] = np.nextafter(error_values[i, j], np.inf)
        arrays['torque_error_bound_n_m'] = error_values
        arrays['reservoir_native_traction_pa'] = reservoir_pressure.array('reservoir_native_traction_pa')
        metadata = dict(schema='atlas.differential-pressure-forcing.v1', network_id=network.network_id,
            geometry_id=geometry_id, time_s=time, plate_ids=list(network.plate_ids), source=f['source'],
            exterior_parent_state_id=exterior_parent_state_id, funding_id=funding.funding_id,
            native_state_id=state.native_state.result_id, spatial_state_id=spatial_state.state_id,
            volume_map_id=f['volume_map_id'], native_plan_id=native.plan_id,
            native_material_source=native.descriptor()['material_source'],
            pressure_reference=native.descriptor().get('pressure_reference'), radial_datum=datum.record(),
            reservoir_closure_id=reservoir_pressure.closure_id, reservoir_native_side=pressure['side'],
            reservoir_pressure=pressure, physical_densities=densities,
            boundary_pose_ids=certificates, cut_face_certificates=cut_records, exact_torque_bounds=exact,
            exact_total_torque_error_bounds_n_m=[[V._encoded(q) for q in row] for row in errors],
            request=dict(max_torque_width_n_m=V._encoded(width), max_operator_error=V._encoded(operator_error), max_leaves=max_leaves),
            integration_leaves=leaves,
            partition='current wall - native wall + imposed reservoir cut - reservoir wall; native discrete reference separate',
            background='uniform radial mantle/support and surface load have zero closed-plate torque; no mantle stock created',
            external_work='reservoir cut loads and natural native pressure are external, not dissipation')
        return _issue(DifferentialPressureForcing, metadata, arrays, budget)
