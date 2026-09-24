"""Source-bound S2/S3/S4 input for a named local planar deformation scenario.

This bridge samples real spherical crust volumes. It neither evolves material nor
solves support. The planar inventory is explicitly volume-equivalent, not a claim
that radial shell thickness equals planar thickness. No mantle age/heat is made up.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from new_world_contract import ContractError, canonical_bytes

_FILE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()
YEAR = 365.25 * 86400.
_DEFAULTS = dict(edge_index=None, fraction=.5, width_m=40000., length_m=20000.,
                 cells_across=4, max_elapsed_s=100000.*YEAR)


def _fail(message):
    raise ContractError('NATIVE_INPUT_REFUSED', message)


def source_hash():
    current = hashlib.sha256(_FILE.read_bytes()).hexdigest()
    if current != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Native-input adapter changed while loaded.')
    return current


def source_binding():
    return {'native_input_sha256': source_hash()}


def _payload_bytes(record):
    # Scientific snapshots are not S1 configuration input. Keep their own bound.
    body = json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')
    if len(body) > 1 << 20:
        _fail('Native input snapshot exceeds its 1 MiB envelope.')
    return body


def _options(options):
    if type(options) is not dict or set(options) - set(_DEFAULTS):
        _fail('Only edge_index, fraction, width_m, length_m, cells_across and max_elapsed_s are supported.')
    result = dict(_DEFAULTS, **options)
    if result['edge_index'] is not None and (type(result['edge_index']) is not int or result['edge_index'] < 0):
        _fail('edge_index must be a nonnegative integer or null.')
    if type(result['cells_across']) is not int or not 1 <= result['cells_across'] <= 64:
        _fail('cells_across must be an integer from 1 to 64.')
    for name in ('fraction', 'width_m', 'length_m', 'max_elapsed_s'):
        value = result[name]
        if type(value) not in (int, float) or not math.isfinite(value):
            _fail(name + ' must be a finite number.')
        result[name] = float(value)
    if not 0 < result['fraction'] < 1:
        _fail('The selected edge fraction must be strictly inside 0..1; junction footprints are unsupported.')
    if any(result[key] <= 0 for key in ('width_m', 'length_m', 'max_elapsed_s')):
        _fail('Positive dimensions and elapsed horizon required.')
    return result


def _arc_distances(point, starts, ends):
    """Vectorised angular distance to finite minor arcs, including endpoints."""
    import numpy as np
    cross = np.cross(starts, ends)
    sine = np.linalg.norm(cross, axis=1)
    if np.any(sine <= math.sqrt(np.finfo(float).eps)):
        _fail('Unresolved near-degenerate/antipodal boundary arc.')
    normal = cross / sine[:, None]
    signed = normal @ point
    projected = point - signed[:, None]*normal
    norm = np.linalg.norm(projected, axis=1)
    good = norm > math.sqrt(np.finfo(float).eps)
    q = projected / np.where(good, norm, 1.)[:, None]
    within = good & (np.einsum('ij,ij->i', np.cross(starts, q), normal) >= 0)
    within &= np.einsum('ij,ij->i', np.cross(q, ends), normal) >= 0
    endpoint = np.minimum(np.arctan2(np.linalg.norm(np.cross(starts, point), axis=1), starts@point),
                          np.arctan2(np.linalg.norm(np.cross(ends, point), axis=1), ends@point))
    return np.where(within, np.arctan2(np.abs(signed), norm), endpoint)


def _footprint(atlas, state, index, opts, *, budget, cancel):
    """A circumscribed cap proves complete ownership; no centre-only admission."""
    import numpy as np
    from atlas_tectonics import SphericalChart, SphericalGeometry
    from atlas_tectonics.geometry import _check_cancel
    _check_cancel(cancel)
    a, b = atlas.vertex_directions[atlas.edge_vertices[index]]
    normal_left = np.cross(a, b)
    sine = float(np.linalg.norm(normal_left))
    angle = math.atan2(sine, float(a@b))
    if sine <= math.sqrt(np.finfo(float).eps):
        _fail('Selected edge is numerically unresolved.')
    normal_left /= sine
    tangent_start = np.cross(normal_left, a)
    centre = a*math.cos(angle*opts['fraction']) + tangent_start*math.sin(angle*opts['fraction'])
    centre /= np.linalg.norm(centre)
    # x points from left plate to right plate; y is the actual directed edge.
    x = -normal_left
    y = np.cross(normal_left, centre)
    radius = atlas.sphere.radius_m
    extent = math.hypot(opts['width_m']/2, opts['length_m']/2)
    cap = math.atan(extent/radius)
    band = 64*np.finfo(float).eps
    if cap >= .05:
        _fail('Local footprint exceeds the explicit 0.05-radian chart envelope.')
    if min(angle*opts['fraction'], angle*(1-opts['fraction'])) <= cap+band:
        _fail('Complete footprint reaches a selected-edge endpoint/junction.')
    others = np.asarray([e for e in atlas.interplate_edges if e != index], dtype=int)
    clearance = math.pi
    if len(others):
        pairs = atlas.vertex_directions[atlas.edge_vertices[others]]
        clearance = float(np.min(_arc_distances(centre, pairs[:, 0], pairs[:, 1])))
        if clearance <= cap+band:
            _fail('Complete footprint may reach another interplate edge; exactly one plate pair required.')
    case = state.case
    features = {g.key:g.geometry for g in case.geometries}
    inside = []
    geology_clearance = math.pi*radius
    for province in case.provinces:
        if province.selector.kind == 'domain':
            continue
        if province.selector.kind != 'geometry':
            _fail('This source bridge requires original domain/geometry crust selectors.')
        included = False
        for key in province.selector.keys:
            geometry = features[key]
            distance = float(geometry.distance_to([centre], boundary=True, budget=budget, cancel=cancel)[0])
            geology_clearance = min(geology_clearance, distance)
            if distance <= radius*(cap+band):
                _fail('Complete footprint may cross/touch a geological boundary; one resolved column required.')
            code = int(geometry.classify([centre], budget=budget, cancel=cancel)[0])
            if code == 0:
                _fail('Geological ownership is numerically ambiguous.')
            included |= code == 1
        if included:
            inside.append(province.province_id)
    column_id = case.resolve_provinces(tuple(inside)).column_id
    column = next(c for c in case.columns if c.column_id == column_id)
    if any(layer.porosity != 0 for layer in column.layers if layer.role != 'lithospheric_mantle'):
        _fail('This dry-crust bridge requires explicitly zero source porosity.')
    if state.bodies:
        _fail('Subsurface bodies require their own full-footprint material bridge.')
    chart = SphericalChart(atlas.sphere, tuple(centre))
    polygons = []
    supports = []
    width, length, count = opts['width_m'], opts['length_m'], opts['cells_across']
    for j in range(count):
        left, right = -width/2 + width*j/count, -width/2 + width*(j+1)/count
        coords = [[left,-length/2], [right,-length/2], [right,length/2], [left,length/2]]
        directions = centre + np.asarray(coords)[:, :1]/radius*x + np.asarray(coords)[:, 1:]/radius*y
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        supports.append(SphericalGeometry.polygon(directions, chart=chart, budget=budget))
        polygons.append(coords)
    return column, tuple(supports), polygons, dict(
        centre=centre.tolist(), basis_x=x.tolist(), basis_y=y.tolist(), radius_m=radius,
        native_chart=chart.descriptor(), cap_radius_rad=cap,
        other_boundary_clearance_m=clearance*radius,
        geological_boundary_clearance_m=geology_clearance,
        whole_footprint_proof='circumscribed cap excludes every other interplate edge, both selected endpoints and every crust-province boundary')


def _promote(state, atlas, budget, cancel):
    from atlas_tectonics import GeologicalCase, InitialConditionState
    case = state.case
    fields = ('sources', 'materials', 'cohorts', 'thermal_profiles', 'columns',
              'provinces', 'precedence', 'geometries', 'faults', 'weak_zones')
    promoted = GeologicalCase(case.case_id, atlas, time_s=case.time_s,
        epoch_id=case.epoch_id, depth_reference_id=case.depth_reference_id,
        source_id=case.source_id, **{key:getattr(case,key) for key in fields}, budget=budget, cancel=cancel)
    return InitialConditionState(promoted, origins=state.origins, cooling_history=state.cooling_history,
        material_bases=state.material_bases, fields=state.fields, bodies=state.bodies,
        body_order=state.body_order, library=state.library, budget=budget, cancel=cancel)


def assemble_input(saved_project, options:dict, *, cancel=None):
    """Produce bounded JSON-safe native inputs, without evolving the saved world.

    fraction is measured along the original directed atlas edge. Auto selection
    tries resolved continental convergence first, then other resolved boundaries,
    without modifying supplied dimensions or the fraction. Initial temperatures
    remain native initial means, not enthalpy or a thermal evolution result.
    """
    import numpy as np
    from atlas_tectonics import PreparedPrecursor, InitialSamplingCell
    from atlas_tectonics.geometry import _check_cancel
    from atlas_tectonics.resources import WorkBudget
    from new_world_project import SavedProject
    from new_world_structure import check_structure
    from new_world_motion import check_motion
    binding = source_binding()
    _check_cancel(cancel)
    opts = _options(options)
    if type(saved_project) is not SavedProject or not saved_project.configuration_compatible:
        _fail('A current compatible SavedProject is required.')
    project = saved_project
    if project.structure is None or project.motion is None:
        _fail('Saved S2 layout, S3 structure and S4 motion are required.')
    plan = project.manifest['plan']
    atlas, structure, motion = project.atlas, project.structure, project.motion
    if project.manifest.get('atlas_id') != atlas.atlas_id:
        _fail('Saved manifest and atlas identity disagree.')
    check_structure(plan, structure, current=True)
    check_motion(plan, atlas, structure, motion, current=True)
    record = motion.descriptor()
    budget = WorkBudget(plan['request']['resources']['max_work_bytes'])
    candidates = []
    for segment in record['segments']:
        if opts['edge_index'] is not None and segment['edge_index'] != opts['edge_index']:
            continue
        if not segment['start_fraction'] < opts['fraction'] < segment['end_fraction']:
            continue
        if len(segment['column_ids']) != 1 or segment['regime'] not in ('incipient-shortening','incipient-extension'):
            continue
        priority = 0 if segment['regime'] == 'incipient-shortening' and segment['crust_types'] == ['continental'] else 1
        candidates.append((priority, segment['edge_index'], segment))
    if not candidates:
        _fail('No resolved motion/crust interval contains the selected edge fraction.')
    candidates.sort(key=lambda entry:entry[:2])
    # One shared allowance includes vectorised edge checks and JSON materialisation.
    with budget.reserve((4 << 20)+1024*atlas.edge_count, category='native-input-adapter'):
        failure = None
        for _, index, segment in candidates:
            _check_cancel(cancel)
            try:
                column, supports, polygons, chart = _footprint(atlas, structure.state, index, opts, budget=budget, cancel=cancel)
                if column.column_id != segment['column_ids'][0]:
                    _fail('Selected saved motion interval and full-footprint crust disagree.')
                break
            except ContractError as exc:
                if exc.code != 'NATIVE_INPUT_REFUSED':
                    raise
                failure = exc
        else:
            raise failure
        initial = _promote(structure.state, atlas, budget, cancel)
        depth = math.fsum(layer.bulk_thickness_m for layer in column.layers if layer.role != 'lithospheric_mantle')
        parcel_ids = tuple('source-strip-'+str(j) for j in range(len(supports)))
        cells = tuple(InitialSamplingCell(name, geometry, 0., depth) for name,geometry in zip(parcel_ids,supports))
        case = initial.case
        with PreparedPrecursor(initial, budget=budget, cancel=cancel) as prepared:
            samples = prepared.sample_cells(cells, frame_id=atlas.sphere.frame_id,
                epoch_id=case.epoch_id, depth_reference_id=case.depth_reference_id, cancel=cancel)
        md = samples.descriptor()
        units = samples.array('unit_code')
        if any(initial.units[int(u)].owner_id != column.column_id or initial.units[int(u)].layer.role == 'lithospheric_mantle' for u in units):
            _fail('Native S5 returned another column or mantle in the crust-only footprint.')
        if np.any(samples.array('phase_kind') != 0):
            _fail('Native S5 crust must not include pore material.')
        codes = samples.array('phase_cohort_code')
        selected = sorted({md['cohort_ids'][int(code)] for code in codes})
        cohort_map = {c.cohort.cohort_id:c.cohort for c in case.cohorts}
        cohorts = [cohort_map[key] for key in selected]
        material_map = {m.material_id:m for m in case.materials}
        densities = [material_map[c.material_id].density_kg_m3 for c in cohorts]
        mantle = material_map.get('rock.peridotite')
        if mantle is None or mantle.density_kg_m3 is None or any(r is None or r <= 0 for r in densities):
            _fail('Existing crust and mantle reference densities are required.')
        rows = samples.array('phase_row')
        row_cells = samples.array('row_cell')
        values = samples.array('phase_volume_m3')
        volume = [[math.fsum(float(values[j]) for j in range(len(values))
            if md['cohort_ids'][int(codes[j])] == key and int(row_cells[rows[j]]) == p)
            for p in range(len(cells))] for key in selected]
        edge = atlas.edge(index)
        left = np.asarray(record['angular_velocities_rad_s'][edge.left_plate_id])
        right = np.asarray(record['angular_velocities_rad_s'][edge.right_plate_id])
        centre, x, y = (np.asarray(chart[key]) for key in ('centre','basis_x','basis_y'))
        radius = atlas.sphere.radius_m
        lv, rv = np.cross(left, centre)*radius, np.cross(right, centre)*radius
        local_left = np.array([lv@x, lv@y]); local_right = np.array([rv@x, rv@y])
        delta = local_right-local_left
        uncertainty = segment['opening_roundoff_m_s']
        if abs(float(delta[0])) <= uncertainty:
            _fail('Selected midpoint normal motion is unresolved.')
        elapsed = opts['max_elapsed_s']
        omega = max(float(np.linalg.norm(left)), float(np.linalg.norm(right)))
        gradient = np.array([[delta[0]/opts['width_m'],0.], [delta[1]/opts['width_m'],0.]])
        velocity = (local_left+local_right)/2
        # Gronwall bound for every affine trajectory and every t in [0,T].
        # This includes common translation and shear, not just the original cap.
        initial_radius = math.hypot(opts['width_m']/2, opts['length_m']/2)
        radius_term = initial_radius+float(np.linalg.norm(velocity))*elapsed
        exponent = float(np.linalg.norm(gradient))*elapsed
        if not math.isfinite(radius_term) or not math.isfinite(exponent) or (
                math.log(radius_term)+exponent >= math.log(radius*math.tan(.05))):
            _fail('Complete affine trajectory bound exceeds the 0.05-radian local scenario envelope.')
        affine_radius = math.exp(exponent)*radius_term
        rigid_cap = chart['cap_radius_rad']+omega*elapsed
        swept_cap = max(rigid_cap, math.atan(affine_radius/radius))
        if swept_cap >= .05:
            _fail('Footprint plus finite Euler sweep exceeds the 0.05-radian local scenario envelope.')
        projected_radius = radius*math.tan(swept_cap)
        speed_error = omega*projected_radius
        metadata = dict(schema='atlas.new-world-native-input.v1', status='WORKING NON-CANON',
            source_binding=binding, options=opts, edge_index=index, edge_id=atlas.edge_ids[index],
            left_plate_id=edge.left_plate_id, right_plate_id=edge.right_plate_id,
            column_id=column.column_id, crust_type=column.crust_type, crust_depth_m=depth,
            chart=chart, atlas_id=atlas.atlas_id, structure_id=structure.structure_id,
            motion_id=motion.motion_id, precursor_state_id=structure.state.state_id,
            initial_condition_id=initial.state_id, initial_condition_definition=initial.descriptor(),
            geological_case_definition=case.descriptor(),
            native_samples=dict(descriptor=md, arrays={key:samples.array(key).tolist() for key in md['arrays']}),
            density_definitions=[asdict(material_map[c.material_id]) for c in cohorts],
            mantle_density_definition=asdict(mantle),
            angular_velocities_rad_s=dict(left=left.tolist(), right=right.tolist()),
            left_velocity_m_s=local_left.tolist(), right_velocity_m_s=local_right.tolist(),
            relative_velocity_m_s=delta.tolist(),
            approximation=dict(model='midpoint Euler velocities distributed affinely across a named finite planar width',
                swept_cap_radius_rad=swept_cap, gnomonic_max_length_scale=1/math.cos(swept_cap)**2,
                gnomonic_max_area_scale=1/math.cos(swept_cap)**3,
                affine_trajectory_radius_bound_m=affine_radius,
                affine_bound='exp(norm(G)*T)*(initial radius + norm(common velocity)*T), all t in [0,T]',
                rigid_euler_swept_cap_radius_rad=rigid_cap,
                per_plate_projected_velocity_variation_bound_m_s=speed_error,
                relative_projected_velocity_variation_bound_m_s=2*speed_error,
                frozen_velocity_path_error_bound_m=speed_error*elapsed,
                bound_scope='all affine parcel trajectories and rigid Euler paths fit the admitted cap; velocity/path errors bound midpoint-frozen rigid kinematics only, not constitutive-model or global plate-boundary error'),
            inventory_semantics='exact native S5 spherical phase/matrix reference volumes; intrinsic solid-volume unknown masks are retained; equivalent planar thickness is V / planar polygon area; no renormalisation',
            density_semantics='supplied constant reference-density scenario, not hot-state mass or an equation of state',
            temperature_semantics='retained native initial volume-weighted temperatures and known masks; no evolved heat/enthalpy',
            physical_scope='prescribed local distributed deformation, not finite-time global plate topology or force prediction')
        result = dict(polygons_m=polygons, parcel_ids=list(parcel_ids), cohorts=[asdict(c) for c in cohorts],
            density_kg_m3=densities, volume_m3=volume, epoch_id=case.epoch_id,
            epoch_time_s=case.time_s, frame_id='local-gnomonic-'+hashlib.sha256(canonical_bytes(chart)).hexdigest(),
            datum_id=case.depth_reference_id, gradient_s=gradient.tolist(), velocity_m_s=velocity.tolist(),
            anchor_m=[0.,0.], max_elapsed_s=elapsed, max_work_bytes=budget.max_bytes,
            mantle_density_kg_m3=mantle.density_kg_m3, metadata=metadata)
        _payload_bytes(result)
        _check_cancel(cancel)
        source_binding()
        return result
