"""Work-conjugate plate/resolved-box mechanics, not a material/global clock.

The prescribed boundary velocities are DERIVED from physical lever arms and
plate owners. A declared angular-rate subspace is a real kinematic constraint;
its reaction is reported separately, never hidden as a torque residual.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import hashlib
import json
import math
from fractions import Fraction

import numpy as np

from . import integration_bridges as B
from . import integration_driving as D
from . import integration_sphere as S
from . import integration_support as U
from . import integration_transfer as T
from ._validation import TectonicsError, frozen
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import PreparedRegionalStokes3D, SIDES, _digest_array
from .resources import WorkBudget


SCHEMA = 'atlas.plate-regional-driving.v1'
ALGEBRA = D.POLICY['algebra_relative']   # existing D1 algebra gate, 1e-11
WORK = 5e-9                           # existing native mechanical-work gate
GEOMETRY_KEYS = ('cells', 'lengths_m', 'scales', 'boundary_types', 'frame_id', 'vertical_datum')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _name(value):
    if type(value) is not str or not value or len(value) > 512:
        raise TectonicsError('bounded explicit identity/source required')
    return value


def _array(value, shape, label):
    a = np.asarray(value, dtype=float)
    if a.shape != shape or not np.isfinite(a).all():
        raise TectonicsError(label+' has an incompatible shape or nonfinite value')
    return a


def _relative(error, *operands):
    scale = max((float(np.max(np.abs(a), initial=0.)) for a in operands), default=0.)
    error = float(np.max(np.abs(error), initial=0.))
    return error/scale if scale else (0. if error == 0 else math.inf)


def _fsum_contract(left, right):
    """Row-wise products, with an operation-derived absolute round-off bound.

    Each binary64 product contributes at most eps times its absolute value;
    fsum's possible final double-rounding contributes at most two further eps.
    Subnormal products get one smallest-subnormal allowance each. Bounds are
    rounded outward. This is arithmetic uncertainty, not a force tolerance.
    """
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    products = a*b
    if not np.isfinite(products).all():
        raise TectonicsError('virtual-work products exceed binary64 range')
    rows = products.reshape(a.shape[0], -1)
    values = np.asarray([math.fsum(map(float, row)) for row in rows])
    magnitudes = np.asarray([math.fsum(abs(float(v)) for v in row) for row in rows])
    bounds = np.nextafter(4*np.finfo(float).eps*magnitudes+
                         rows.shape[1]*np.nextafter(0., 1.), math.inf)
    return values, bounds


def _accounted_relative(error, bound, *operands):
    """Original relative gate after only the separately reported arithmetic."""
    error = float(np.max(np.abs(error), initial=0.))
    bound = float(np.max(bound, initial=0.))
    scale = max((float(np.max(np.abs(a), initial=0.)) for a in operands), default=0.)
    excess = max(0., error-bound)
    return excess/scale if scale else (0. if excess == 0 else math.inf)


def _reservoir_pressure_work(native, velocity, pressure, budget):
    """Exact work of pressure-sample projection on the represented FE field.

    This is a boundary-load representation account. It neither adds heat nor
    claims that binary quadrature nodes/weights are exact continuum geometry.
    The native pressure/reference bookkeeping remains a separate decomposition.
    """
    from .integration_wall_measures import _decode
    from .integration_volume import _encoded
    side = pressure['side']; axis = 'xyz'.index(side[0]); sign = 1 if side[1] == '0' else -1
    cells, shape, weights, _ = native._mesh._face(side)
    exact = pressure['exact_native_pressure_pa']
    residual = pressure['native_pressure_projection_residual_pa']
    if len(exact) != len(cells)*9 or len(residual) != len(exact):
        raise TectonicsError('reservoir pressure projection account differs from native quadrature')
    with budget.reserve(65536+32*len(_json((exact, residual)))+4096*len(exact),
                        category='reservoir-pressure-work-account'):
        work = error = bound = Fraction(0)
        area_scale = Fraction(native._scales.length_m)**2
        for face, cell in enumerate(cells):
            nodes = native._mesh.velocity_cells[cell]
            values = tuple(Fraction(float(v)) for v in velocity[nodes, axis])
            for q, row in enumerate(shape):
                normal = sign*sum((Fraction(float(v))*u for v, u in zip(row, values)), Fraction(0))
                weight = Fraction(float(weights[q]))*area_scale
                p, delta = _decode(exact[9*face+q]), _decode(residual[9*face+q])
                work += (p+delta)*normal*weight
                error += delta*normal*weight
                bound += abs(delta*normal*weight)
        return dict(full_native_reservoir_pressure_work_w=_encoded(work),
            declared_pressure_work_on_represented_quadrature_w=_encoded(work-error),
            pressure_projection_work_residual_w=_encoded(error),
            pressure_projection_work_abs_bound_w=_encoded(bound),
            rule='exact contraction of literal pressure/projection residual with represented Q2 velocity and native Gauss weights; external work, not heat')


def _contains(cells, point):
    ray = T._integers([point])[0]
    return any(all(T._dot(T._cross(a, b), ray) >= 0
                   for a, b in zip(cell, cell[1:]+cell[:1])) for cell in cells)


def _closed_volume_basis(full, cells, lengths):
    """Exact integral of the represented Q2 boundary field, not fitted modes.

    Composite Simpson weights integrate each quadratic element face exactly.
    The sole constraint is integral_boundary(v dot n)=0 in the closed box.
    Binary64 input coordinates/modes retain their exact represented values.
    """
    from . import integration_volume as V
    shape = tuple(2*n+1 for n in cells)
    flux = [Fraction(0)]*6
    for axis in range(3):
        tangent = [j for j in range(3) if j != axis]
        area = Fraction(lengths[tangent[0]])*Fraction(lengths[tangent[1]])
        weights = [tuple(Fraction(1 if i in (0, 2*cells[j]) else (4 if i % 2 else 2), 6*cells[j])
                         for i in range(shape[j])) for j in tangent]
        for end in (0, 1):
            for i, wi in enumerate(weights[0]):
                for j, wj in enumerate(weights[1]):
                    at = [0]*3; at[axis] = end*(shape[axis]-1); at[tangent[0]] = i; at[tangent[1]] = j
                    node = np.ravel_multi_index(tuple(at), shape)
                    for k in range(6):
                        flux[k] += (2*end-1)*area*wi*wj*Fraction(float(full[k, node, axis]))
    if not any(flux):
        return np.eye(6), dict(rule='exact Q2 boundary flux is zero for all six angular modes', exact_flux=list(map(V._encoded, flux)))
    pivot = max(range(6), key=lambda i: abs(flux[i]))
    other = [i for i in range(6) if i != pivot]
    exact = [[Fraction(int(i == j)) for j in other] for i in range(6)]
    exact[pivot] = [-flux[j]/flux[pivot] for j in other]
    raw = np.asarray([[float(q) for q in row] for row in exact])
    return raw, dict(rule='exact Q2 closed-box volume constraint; no imposed directional resistance',
        exact_flux=list(map(V._encoded, flux)), pivot=pivot,
        exact_basis=[[V._encoded(q) for q in row] for row in exact],
        projection_residual=[[V._encoded(Fraction(float(v))-q) for v, q in zip(row, ex)] for row, ex in zip(raw, exact)])


class PlateBoundaryLift:
    """An exact affine 3-D embedding with physically derived boundary modes.

    ``origin_local_m`` places native (0,0,0) in the Footprint's existing static
    LocalCartesianFrame. ``node_face_ids`` names the source face at every node
    with prescribed components; all other entries MUST be None. Each mapped
    point is checked against that face's exact minor-arc support and radial
    depth. No supplied displacement modes, approximate lever arms, snapping or
    inferred plate owner are accepted.

    ``angular_rate_basis`` is 6 by k, in boundary (left,right) plate order and
    the actual sphere XYZ axes: omega_pair = N q. N=I is unrestricted. Any
    smaller subspace requires an explicit constraint source. This is only a
    boundary-point kinematic map, not a volume/material allocation or a claim
    that the box represents the whole footprint.
    """
    def __setattr__(self, name, value):
        if not name.startswith('_') and hasattr(self, name):
            raise TectonicsError('physical plate lift identities are immutable')
        object.__setattr__(self, name, value)

    def __init__(self, network, native, footprint, boundary_id, *, origin_local_m,
                 node_face_ids, angular_rate_basis, map_source, constraint_source, budget, volume_map=None,
                 current_pose=None):
        self._guard = None
        if (type(network) is not S.SphereNetwork or type(native) is not PreparedRegionalStokes3D
                or type(footprint) is not B.Footprint or type(budget) is not WorkBudget
                or native._resource is not budget):
            raise TectonicsError('issued network, prepared native plan, footprint and one shared budget required')
        definition = native.descriptor()
        nv = math.prod(2*n+1 for n in definition['cells'])
        self._guard = budget.reserve(65536+16384*nv+8*network.nbytes, category='plate-regional-lift')
        self._guard.__enter__()
        try:
            self._budget = budget
            self._current_pose = None
            if current_pose is not None:
                from .integration_current_force_pose import CurrentForcePose
                if (type(current_pose) is not CurrentForcePose or current_pose._resource is not budget or
                        current_pose.descriptor()['source']['network_id'] != network.network_id or volume_map is None):
                    raise TectonicsError('current plate lift requires issued pose and actual physical volume map')
                self._current_pose = current_pose.descriptor()
            if footprint.representation != '3d' or footprint.region_id != definition['frame_id']:
                raise TectonicsError('physical lift requires the named full-3D footprint/native frame')
            boundaries = {b.boundary_id: b for b in network.boundaries}
            if boundary_id not in boundaries:
                raise TectonicsError('unknown replaced boundary')
            boundary = boundaries[boundary_id]
            self.plate_ids = (boundary.left_plate_id, boundary.right_plate_id)
            frame, projection, rings, _, _ = B._charted(network, footprint)
            nodes = native.coordinates('velocity')
            origin = _array(origin_local_m, (3,), 'box origin')
            points = frame.positions_to_cartesian(nodes+origin, budget=budget)
            physical_binding = None
            if volume_map is not None:
                from .integration_regional_evolution import RegionalVolumeMap
                if type(volume_map) is not RegionalVolumeMap:
                    raise TectonicsError('a proved RegionalVolumeMap is required, not a copied binding label')
                volume = volume_map.record()
                if (volume['source']['network_id'] != network.network_id or
                        volume['request']['footprint'] != footprint.record() or
                        volume['embedding']['frame'] != frame.descriptor() or
                        volume['embedding']['origin_local_m'] != origin.tolist()):
                    raise TectonicsError('physical lift and material map have different source geometry')
                physical_binding = volume_map.native_binding(native)
                if current_pose is not None and volume['source'] != self._current_pose['source']:
                    raise TectonicsError('current pose and volume map have different physical source')
                if physical_binding['physical_points_sha256'] != _digest_array(points):
                    raise TectonicsError('physical lift and material map disagree on actual node positions')
            depth = network.sphere.radius_m-np.linalg.norm(points, axis=1)
            mask = native.velocity_mask().reshape(nv, 3)
            held = np.any(mask, axis=1)
            if (np.any(depth[held] < footprint.depth_top_m) or
                    np.any(depth[held] > footprint.depth_bottom_m)):
                raise TectonicsError('mapped boundary point lies outside the declared physical depth')
            if type(node_face_ids) is not tuple or len(node_face_ids) != nv:
                raise TectonicsError('one explicit face owner or None per native velocity node required')
            cells = {f: U.cells_of_rings(r) for f, r in rings.items()}
            owners = np.full(nv, -1, dtype=np.int64)
            for i, face in enumerate(node_face_ids):
                if not held[i]:
                    if face is not None:
                        raise TectonicsError('unconstrained native node must not claim a plate boundary owner')
                    continue
                if face not in cells or network.face_plate(face) not in self.plate_ids:
                    raise TectonicsError('boundary owner is outside the footprint or replaced plate pair')
                if not (_contains(cells[face], points[i]) if current_pose is None else
                        current_pose.contains(cells[face], points[i])):
                    raise TectonicsError('physical boundary point lies outside its declared source face')
                owners[i] = self.plate_ids.index(network.face_plate(face))
            if set(owners[held]) != {0, 1}:
                raise TectonicsError('both source plates must own prescribed boundary nodes')
            full = np.zeros((6, nv, 3))
            for side in range(2):
                for axis in range(3):
                    velocity = frame.vectors_from_cartesian(np.cross(np.eye(3)[axis], points), budget=budget)
                    full[3*side+axis] = np.where(mask & (owners == side)[:, None], velocity, 0.)
            flux_constraint = None
            if type(angular_rate_basis) is str and angular_rate_basis == 'closed-native-volume':
                raw, flux_constraint = _closed_volume_basis(full, definition['cells'], definition['lengths_m'])
            else:
                raw = np.asarray(angular_rate_basis, dtype=float)
            if raw.ndim != 2 or raw.shape[0] != 6 or not 1 <= raw.shape[1] <= 6 or not np.isfinite(raw).all():
                raise TectonicsError('angular-rate basis must be a finite 6 by k array, 1 <= k <= 6')
            # D1's existing SPD/conditioning checks; no pseudoinverse or dropped mode.
            D.solve_torque(raw.T@raw, np.zeros(raw.shape[1]))
            if raw.shape[1] < 6:
                _name(constraint_source)
            elif constraint_source is not None:
                raise TectonicsError('a full-rank six-rate basis has no kinematic constraint')
            _name(map_source)
            modes = np.einsum('ak,aij->kij', raw, full)
            if any(not native.net_flux_neutral(v) for v in modes):
                raise TectonicsError('physical angular-rate basis has incompatible native boundary volume flux; declare a valid constraint, never repair modes')
            self._full, self._modes, self._basis = frozen(full), frozen(modes), frozen(raw)
            self._points, self._mask = frozen(points), mask.copy()
            self._geometry = {k: definition[k] for k in GEOMETRY_KEYS}
            self._material_source = definition['material_source']
            # The exterior retains its declared reference-pressure drives.
            # A native physical pressure may therefore be coupled only through
            # the incremental reaction of this exact discrete reference split.
            # Bind the field AND its load convention, not just a source label.
            self._pressure_reference = definition.get('pressure_reference')
            described = dict(schema='atlas.physical-plate-boundary-lift.v1',
                network_id=network.network_id, sphere_frame=network.sphere.descriptor(),
                boundary_id=boundary_id, plate_ids=list(self.plate_ids), footprint=footprint.record(),
                frame=frame.descriptor(), projection=B._plain(projection), geometry=self._geometry,
                origin_local_m=origin.tolist(), node_face_ids=list(node_face_ids),
                angular_rate_basis=raw.tolist(), map_source=map_source, constraint_source=constraint_source,
                physical_points_sha256=_digest_array(points), modes_sha256=_digest_array(modes),
                rule='local components of omega_owner cross actual physical position; only prescribed components',
                scope='physical boundary-point embedding, not a spherical volume/material map')
            if physical_binding is not None:
                described.update(schema='atlas.physical-plate-boundary-lift.v2',
                    physical_volume_binding=physical_binding,
                    scope='physical boundary-point and contained volume geometry share one embedding; '
                          'not finite open-wall ownership or a joined global time step')
            if self._pressure_reference is not None:
                described['pressure_reference'] = self._pressure_reference
            if self._current_pose is not None:
                described['current_pose'] = self._current_pose
            if flux_constraint is not None:
                described['closed_volume_constraint'] = flux_constraint
            self._definition = _json(described)
            self.lift_id = hashlib.sha256(self._definition).hexdigest()
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        if self._guard is None:
            raise TectonicsError('plate boundary lift is closed')
        return dict(lift_id=self.lift_id, **json.loads(self._definition))

    def close(self):
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self.descriptor()
        return self

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class PlateRegionalResult:
    mechanical: RegionalMechanicalSnapshot
    exchange: RegionalMechanicalSnapshot


class PreparedRegionalDriving:
    """Condense an actual D1 exterior, then reuse the native finite-mode solve.

    D.balance itself is unchanged. Its small exterior solve is used to obtain
    authentic, source-bound force terms; this port never reinterprets that
    provisional omega as the coupled answer. No reduced/fixed reaction may also
    own the replaced boundary. Nonlinear D2 belts are outside this linear port.

    coupling() can be passed straight to RegionalEvolution3D.advance.
    reconstruct() consumes either actual endpoint snapshot WITHOUT another solve
    or heating operation. Geometry and material-source identities must match;
    viscosity may change under that same source's declared thermal law.
    """
    def __setattr__(self, name, value):
        if not name.startswith('_') and hasattr(self, name):
            raise TectonicsError('prepared regional driving identities are immutable')
        object.__setattr__(self, name, value)

    def __init__(self, network, forcing, exterior, prepared, lift, *, budget,
                 pressure_correction=None, pressure_native=None, viscous_only_radial_increment=False,
                 current_background=None, differential_pressure=None,
                 exterior_angular_rate_basis=None, exterior_constraint_source=None,
                 global_angular_rate_basis=None, global_constraint_source=None):
        self._guard = None
        from .integration_differential_trace import DifferentialPlateBoundaryLift
        if (type(lift) not in (PlateBoundaryLift, DifferentialPlateBoundaryLift) or type(budget) is not WorkBudget or lift._budget is not budget
                or type(exterior) is not D.Balance or type(prepared) is not D.Prepared
                or type(forcing) is not D.Forcing or type(network) is not S.SphereNetwork):
            raise TectonicsError('actual D1 balance/operator/forcing, physical lift and shared budget required')
        self._budget, self._lift = budget, lift
        self._owned_pressure = None
        self._current_background = None
        self._differential_pressure = None
        self._natural_traction_binding = None
        if type(viscous_only_radial_increment) is not bool:
            raise TectonicsError('viscous-only radial increment must be explicitly true or false')
        self._viscous_only = viscous_only_radial_increment
        if exterior.radial_pressure is not None and pressure_correction is None and not self._viscous_only:
            raise TectonicsError('radial exterior needs current owned pressure correction or explicit viscous-only zero-load compatibility')
        if self._viscous_only and (exterior.radial_pressure is None or pressure_correction is not None):
            raise TectonicsError('viscous-only compatibility applies only to the uncorrected radial exterior')
        ld = lift.descriptor()
        if (ld['network_id'] != network.network_id or exterior.network_id != network.network_id
                or prepared.network_id != network.network_id or exterior.prepared_id != prepared.prepared_id
                or exterior.forcing_id != forcing.forcing_id
                or prepared.prepared_id != D._expected_prepared_id(network, forcing)):
            raise TectonicsError('stale exterior network, forcing, operator or physical lift')
        boundary = ld['boundary_id']
        if (forcing.belts or exterior.belt is not None or boundary in dict(forcing.interface_k_pa_s)
                or boundary in dict(forcing.regional_reactions)):
            raise TectonicsError('replaced boundary has another resistance/reaction, or a nonlinear belt is present')
        if exterior.parent_state_id is None or exterior.interval is None:
            raise TectonicsError('the exterior must bind its actual parent and interval')
        physical = ld.get('physical_volume_binding')
        if (physical is not None and differential_pressure is None and
                exterior.parent_state_id != physical['source']['sphere_state_id']):
            raise TectonicsError('the exterior balance and physical material map name different parent states')
        n, nv = 3*len(network.plate_ids), len(lift._points)
        self._guard = budget.reserve(65536+8*(12*n*n+128*nv+64*n), category='plate-regional-driving')
        self._guard.__enter__()
        try:
            self._matrix = prepared.matrix.copy()
            b = np.zeros((len(network.plate_ids), 3))
            for term in exterior.terms.values():       # same D.balance assembly order
                b += term
            if current_background is not None:
                from .integration_current_force_pose import CurrentForceBackground
                if type(current_background) is not CurrentForceBackground or current_background._resource is not budget:
                    raise TectonicsError('issued current force background on the same budget is required')
                current = current_background.descriptor()
                if (lift._current_pose != current['pose'] or current['exterior_balance_id'] != exterior.balance_id or
                        current['exterior_prepared_id'] != prepared.prepared_id or pressure_correction is None):
                    raise TectonicsError('current force/drag geometry, physical lift and pressure ownership disagree')
                self._matrix = current_background.array('resistance_j_s').copy()
                b = current_background.array('force_n_m').copy()
                self._current_background = current
            elif lift._current_pose is not None:
                raise TectonicsError('a current-pose lift cannot consume archived force/drag axes')
            if differential_pressure is not None:
                from .integration_differential_pressure import DifferentialPressureForcing
                from .integration_pressure_coupling import reference_torque
                if (type(differential_pressure) is not DifferentialPressureForcing or
                        differential_pressure._resource is not budget or
                        type(lift) is not DifferentialPlateBoundaryLift or
                        type(pressure_native) is not PreparedRegionalStokes3D or pressure_native._resource is not budget or
                        pressure_correction is not None or current_background is not None or self._viscous_only or
                        exterior.radial_pressure is not None or exterior.columns_id is not None or forcing.gamma is not None):
                    raise TectonicsError('differential pressure requires its typed current trace and pressure-free exterior')
                current = differential_pressure.descriptor()
                pd = pressure_native.descriptor()
                trace = ld['trace']
                geometry_id = (trace['interval_predictor']['force_geometry_id'] if 'interval_predictor' in trace
                               else trace.get('current_geometry_id', trace.get('interval_id')))
                if (current['network_id'] != network.network_id or current['geometry_id'] != geometry_id or
                        current['plate_ids'] != list(network.plate_ids) or
                        current['exterior_parent_state_id'] != exterior.parent_state_id or
                        current['time_s'] not in exterior.interval[2:] or
                        current['time_s'] != network.time_s or
                        physical is None or current['volume_map_id'] != physical['volume_map_id'] or
                        current['source']['sphere_state_id'] != physical['source']['sphere_state_id'] or
                        current['pressure_reference'] != lift._pressure_reference or
                        any(pd[k] != v for k, v in lift._geometry.items()) or
                        pd['material_source'] != current['native_material_source'] or
                        pressure_native.plan_id != current['native_plan_id'] or
                        pd['material_source'] != lift._material_source):
                    raise TectonicsError('differential pressure has stale source, physical support, clock or reference')
                for key in ('native_state_id', 'spatial_state_id', 'reservoir_closure_id'):
                    _name(current[key])
                shape = (len(network.plate_ids), 3)
                wall = _array(differential_pressure.array('hydrostatic_wall_torque_n_m'), shape, 'current wall torque')
                owned = _array(differential_pressure.array('native_owned_wall_torque_n_m'), shape, 'owned wall torque')
                cut = _array(differential_pressure.array('reservoir_cut_torque_n_m'), shape, 'prescribed cut torque')
                error = _array(differential_pressure.array('torque_error_bound_n_m'), shape, 'pressure torque error')
                if np.any(error < 0):
                    raise TectonicsError('pressure integration error must be explicitly nonnegative')
                reference = reference_torque(pressure_native, lift)
                reference_full = np.zeros(shape)
                for plate, torque in zip(lift.plate_ids, reference):
                    reference_full[network.plate_ids.index(plate)] = torque
                b = np.asarray([math.fsum(values) for values in
                    zip(b.ravel(), wall.ravel(), -owned.ravel(), cut.ravel(), -reference_full.ravel())]).reshape(shape)
                side = current['reservoir_native_side']
                if side != trace['open_side'] or pd['boundary_types'][side] != ['traction']*3:
                    raise TectonicsError('reservoir closure differs from the actual natural boundary')
                traction = _array(differential_pressure.array('reservoir_native_traction_pa'),
                                  pressure_native.coordinates(side).shape, 'full physical reservoir traction')
                self._natural_traction_binding = dict(schema='atlas.natural-traction-binding.v1',
                    source=current['reservoir_closure_id'], side=side, traction_sha256=_digest_array(traction))
                self._differential_pressure = dict(forcing=current, reference_resisting_torque_n_m=reference.tolist(),
                    natural_traction_binding=self._natural_traction_binding,
                    equation='M omega + (r_full-r_ref) = b_nonpressure + current_wall - current_owned_wall + reservoir_cut - r_ref')
            elif pressure_correction is not None:
                from .integration_pressure_coupling import OwnedPressureCorrection, reference_torque
                if (type(pressure_correction) is not OwnedPressureCorrection or
                        type(pressure_native) is not PreparedRegionalStokes3D or pressure_native._resource is not budget or
                        pressure_correction._resource is not budget):
                    raise TectonicsError('owned pressure correction and actual shared-budget native operator required')
                correction = pressure_correction.descriptor()
                pd = pressure_native.descriptor()
                if correction.get('current_pose') != lift._current_pose:
                    raise TectonicsError('current pressure and physical plate lift use different poses')
                from .integration_wall_measures import _decode
                clock_matches = (correction['time_s'] in exterior.interval[2:] if lift._current_pose is None else
                    Fraction(correction['time_s']) == _decode(lift._current_pose['time_s']))
                if (exterior.radial_pressure is None or
                        exterior.radial_pressure['port_id'] != correction['base_port_id'] or
                        correction['source']['network_id'] != network.network_id or
                        correction['plate_ids'] != list(network.plate_ids) or
                        correction['source']['sphere_state_id'] != exterior.parent_state_id or
                        not clock_matches or
                        any(pd[k] != v for k, v in lift._geometry.items()) or
                        pd['material_source'] != correction['native_plan_id'] or
                        pd['material_source'] != lift._material_source):
                    raise TectonicsError('owned pressure uses stale source, radial trace, clock or native geometry')
                if physical is None or physical['volume_map_id'] != correction['volume_map_id']:
                    raise TectonicsError('owned wall pressure requires the same actual physical volume map')
                b += pressure_correction.array('physical_exterior_correction_n_m')
                reference = reference_torque(pressure_native, lift)
                for plate, torque in zip(lift.plate_ids, reference):
                    b[network.plate_ids.index(plate)] -= torque
                self._owned_pressure = dict(correction=correction,
                    reference_resisting_torque_n_m=reference.tolist(),
                    equation='M omega + (r_full-r_ref) = b_D1 + density_update - owned_wall - r_ref')
            elif pressure_native is not None:
                raise TectonicsError('pressure native operator requires an issued owned pressure correction')
            self._b = b.ravel()
            a = np.array([3*network.plate_ids.index(p)+j for p in lift.plate_ids for j in range(3)])
            other = np.array([j for j in range(n) if j not in set(a)], dtype=np.int64)
            self._a, self._other = a, other
            self._other_basis = None
            self._global_basis = None
            exterior_subspace = None
            global_subspace = None
            if global_angular_rate_basis is not None:
                raw = np.asarray(global_angular_rate_basis, dtype=float)
                if (exterior_angular_rate_basis is not None or exterior_constraint_source is not None or
                        raw.shape != (n, lift._basis.shape[1]) or not np.isfinite(raw).all() or
                        not np.array_equal(raw[a], lift._basis)):
                    raise TectonicsError('global angular basis must match the issued pair basis exactly and exclude exterior subspaces')
                D.solve_torque(raw.T@raw, np.zeros(raw.shape[1]))
                _name(global_constraint_source)
                self._global_basis = frozen(raw)
                global_subspace = dict(plate_ids=list(network.plate_ids), angular_rate_basis=raw.tolist(),
                    constraint_source=global_constraint_source,
                    rule='physical pre-solve global constraint; full rejected torques retained; no rate projection')
            elif global_constraint_source is not None:
                raise TectonicsError('global constraint source requires its explicit angular basis')
            if exterior_angular_rate_basis is not None:
                raw = np.asarray(exterior_angular_rate_basis, dtype=float)
                if (raw.ndim != 2 or raw.shape[0] != len(other) or
                        not 1 <= raw.shape[1] < len(other) or not np.isfinite(raw).all()):
                    raise TectonicsError('explicit exterior angular basis must be finite, independent and a proper subspace')
                D.solve_torque(raw.T@raw, np.zeros(raw.shape[1]))
                _name(exterior_constraint_source)
                self._other_basis = frozen(raw)
                exterior_subspace = dict(plate_ids=[p for p in network.plate_ids if p not in lift.plate_ids],
                    angular_rate_basis=raw.tolist(), constraint_source=exterior_constraint_source,
                    rule='physical pre-solve constraint; rejected torques retained; no post-solve rate projection')
            elif exterior_constraint_source is not None:
                raise TectonicsError('exterior constraint source requires its explicit angular basis')
            Maa = self._matrix[np.ix_(a, a)]
            ba = self._b[a]
            if self._global_basis is not None:
                # All global rates are functions of the SAME native mode q.
                # Thus virtual work is q.T B.T(M B q + r - b); no independent
                # exterior solve or post-solve equality constraint is present.
                self._other_base, self._other_response = np.zeros(len(other)), np.zeros((len(other), 6))
                self._resistance = frozen(self._global_basis.T@self._matrix@self._global_basis)
                self._drive = frozen(self._global_basis.T@self._b)
            elif len(other):
                Mbb = self._matrix[np.ix_(other, other)]
                Mba = self._matrix[np.ix_(other, a)]
                # Each solve retains the existing D1 conditioning/residual gate.
                if self._other_basis is None:
                    self._other_base = D.solve_torque(Mbb, self._b[other])[0]
                    self._other_response = np.column_stack([D.solve_torque(Mbb, c)[0] for c in Mba.T])
                else:
                    N = self._other_basis
                    reduced = N.T@Mbb@N
                    self._other_base = N@D.solve_torque(reduced, N.T@self._b[other])[0]
                    self._other_response = N@np.column_stack([D.solve_torque(reduced, c)[0] for c in (N.T@Mba).T])
                Mab = self._matrix[np.ix_(a, other)]
                eff, rhs = Maa-Mab@self._other_response, ba-Mab@self._other_base
            else:
                self._other_base, self._other_response = np.zeros(0), np.zeros((0, 6))
                eff, rhs = Maa, ba
            if self._global_basis is None:
                self._resistance = frozen(lift._basis.T@eff@lift._basis)
                self._drive = frozen(lift._basis.T@rhs)
            D.solve_torque(self._resistance, self._drive)
            described = dict(schema=SCHEMA, network_id=network.network_id,
                parent_state_id=exterior.parent_state_id, interval=list(exterior.interval),
                exterior_balance_id=exterior.balance_id, exterior_prepared_id=prepared.prepared_id,
                forcing_id=forcing.forcing_id, plate_ids=list(network.plate_ids), lift=ld,
                material_source=lift._material_source, external_force_sha256=_digest_array(self._drive),
                external_resistance_sha256=_digest_array(self._resistance),
                method='exact D1 Schur elimination; declared angular-rate subspace; native force coupling',
                scope='same-time mechanics only; no active material ownership, global clock or heat deposit')
            if self._owned_pressure is not None:
                described['owned_pressure_partition'] = self._owned_pressure
            if exterior_subspace is not None:
                described['exterior_angular_subspace'] = exterior_subspace
            if global_subspace is not None:
                described['global_angular_subspace'] = global_subspace
                described['method'] = 'declared full global virtual-work basis; native force coupling'
            if self._differential_pressure is not None:
                described['differential_pressure_partition'] = self._differential_pressure
                described['time_s'] = self._differential_pressure['forcing']['time_s']
                described['motion_scope'] = 'actual individual plate trace; interval transport requires its matching differential physical support'
            if self._current_background is not None:
                described['current_background'] = self._current_background
                described['time_s'] = self._owned_pressure['correction']['time_s']
                described['motion_scope'] = ('individual solved plate rates are regional boundary-mode responses; '
                    'only the separately declared common trajectory advances the exterior support')
            if self._viscous_only:
                described['radial_increment_scope'] = 'viscous-only; zero body and natural traction; no evolution coupling export'
            self._definition = _json(described)
            self.driving_id = hashlib.sha256(self._definition).hexdigest()
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        self._lift.descriptor()
        if self._guard is None:
            raise TectonicsError('plate regional driving is closed')
        return dict(driving_id=self.driving_id, **json.loads(self._definition))

    def coupling(self):
        if self._viscous_only:
            raise TectonicsError('viscous-only radial compatibility cannot export a coupling to thermal/gravity evolution')
        return self._coupling()

    def _coupling(self):
        self.descriptor()
        values = dict(boundary_modes_m=self._lift._modes.copy(),
                    external_generalized_force_j=self._drive.copy(),
                    external_resistance_j_s=self._resistance.copy(), source=self.driving_id)
        if self._lift._pressure_reference is not None:
            values['pressure_reference_id'] = self._lift._pressure_reference['reference_id']
        if self._natural_traction_binding is not None:
            values['natural_traction_binding'] = dict(self._natural_traction_binding)
        return values

    def reconstruct(self, mechanical, *, parent_state_id, time_s):
        definition = self.descriptor()
        if (time_s not in definition['interval'][2:] if self._current_background is None else
                time_s != definition['time_s']):
            raise TectonicsError('native time must be an endpoint of the bound exterior interval')
        if type(mechanical) is not RegionalMechanicalSnapshot:
            raise TectonicsError('an actual native mechanical snapshot is required')
        record = mechanical.descriptor()
        request, plan = record.get('request', {}), record.get('plan', {})
        if self._owned_pressure is not None:
            current = self._owned_pressure['correction']
            if parent_state_id != current['native_state_id'] or time_s != current['time_s']:
                raise TectonicsError('owned pressure must be refreshed from this actual current native state and time')
        if self._differential_pressure is not None:
            current = self._differential_pressure['forcing']
            if parent_state_id != current['native_state_id'] or time_s != current['time_s']:
                raise TectonicsError('differential pressure must use this actual current native state and time')
        coupling = request.get('coupling', {})
        expected = dict(source=self.driving_id, modes_sha256=_digest_array(self._lift._modes),
            external_force_sha256=_digest_array(self._drive),
            external_resistance_sha256=_digest_array(self._resistance))
        if self._lift._pressure_reference is not None:
            expected['pressure_reference_id'] = self._lift._pressure_reference['reference_id']
        if self._natural_traction_binding is not None:
            expected['natural_traction_binding'] = self._natural_traction_binding
        if (any(coupling.get(k) != v for k, v in expected.items())
                or any(plan.get(k) != v for k, v in self._lift._geometry.items())
                or plan.get('pressure_reference') != self._lift._pressure_reference
                or plan.get('material_source') != self._lift._material_source
                or request.get('parent_state_id') != parent_state_id or request.get('time_s') != time_s):
            raise TectonicsError('native result has stale coupling, geometry, pressure reference, material source, parent or time')
        k, nv = self._lift._basis.shape[1], len(self._lift._points)
        with self._budget.reserve(65536+mechanical.nbytes+8*(128*nv+32*len(self._b)),
                                  category='plate-regional-result'):
            q = _array(mechanical.array('generalized_rates_s_inv'), (k,), 'native rates')
            r = _array(mechanical.array('velocity_constraint_reaction_n'), (nv, 3), 'native reaction')
            u = _array(mechanical.array('velocity_m_s'), (nv, 3), 'native velocity')
            pair = self._lift._basis@q
            imposed = np.einsum('a,aij->ij', pair, self._lift._full)
            actual = np.where(self._lift._mask, u, 0.)
            if _relative(actual-imposed, actual, imposed) > ALGEBRA:
                raise TectonicsError('native boundary velocity is not the physical plate lift (nonzero base velocity is unsupported)')
            recorded_force = mechanical.array('generalized_regional_force_j')
            datum_account = None
            if 'datum_free_velocity_constraint_reaction_n' in mechanical.array_names:
                free = _array(mechanical.array('datum_free_velocity_constraint_reaction_n'), (nv, 3), 'datum-free reaction')
                datum = _array(mechanical.array('pressure_datum_velocity_constraint_reaction_n'), (nv, 3), 'datum reaction')
                # Publication adds these operands (plus optional analytic
                # hydrostatic reaction); never recover the small free field by
                # subtracting the large datum from the rounded full reaction.
                addition = 4*np.finfo(float).eps*(np.abs(free)+np.abs(datum)+np.abs(r))
                if np.any(np.abs(r-free-datum) > addition):
                    raise TectonicsError('full and separated pressure-datum reactions disagree')
                free_pair, free_error = _fsum_contract(self._lift._full, free)
                datum_pair, datum_error = _fsum_contract(self._lift._full, datum)
                regional_pair = free_pair+datum_pair
                pair_error = free_error+datum_error+2*np.finfo(float).eps*(np.abs(free_pair)+np.abs(datum_pair))
                direct, direct_error = _fsum_contract(self._lift._modes, free)
                # The native datum branch uses this same fsum contraction;
                # the original relative force gate is therefore not inflated
                # by the large pressure datum or by regrouped cancellation.
                if _relative(direct-recorded_force, direct, recorded_force) > ALGEBRA:
                    raise TectonicsError('returned regional force does not reproduce physical virtual work')
                generalized, regroup_error = _fsum_contract(self._lift._basis.T, free_pair)
                regroup_error += np.abs(self._lift._basis.T)@free_error
                represented_modes = np.einsum('ak,aij->kij', self._lift._basis, self._lift._full)
                mode_error = np.zeros(k)
                for mode in range(k):
                    exactish, coefficient_error = _fsum_contract(
                        self._lift._full.reshape(6, -1).T, self._lift._basis[:, mode])
                    difference = np.abs(represented_modes[mode].ravel()-exactish)+coefficient_error
                    mode_error[mode] = math.fsum(float(v) for v in difference*np.abs(free).ravel())
                regroup_bound = np.nextafter(regroup_error+direct_error+mode_error, math.inf)
                if _accounted_relative(generalized-direct, regroup_bound, generalized, direct) > ALGEBRA:
                    raise TectonicsError('physical plate-mode regrouping exceeds accounted arithmetic')
                datum_generalized, datum_projection_error = _fsum_contract(self._lift._basis.T, datum_pair)
                datum_account = dict(
                    force_contraction_absolute_residual_j=float(np.max(np.abs(generalized-recorded_force))),
                    force_contraction_roundoff_bound_j=float(np.max(regroup_bound)),
                    datum_generalized_force_j=datum_generalized.tolist(),
                    datum_projection_roundoff_bound_j=(datum_projection_error+np.abs(self._lift._basis.T)@datum_error).tolist(),
                    rule='full physical reaction retained; datum-free force contracted without subtractive cancellation')
            else:
                regional_pair, pair_error = _fsum_contract(self._lift._full, r)
                generalized, regroup_error = _fsum_contract(self._lift._basis.T, regional_pair)
                # Preserve the old native no-datum contraction and its output
                # identity. Compare the recorded force with those exact same
                # supplied operands before separately bounding regrouping.
                direct = np.einsum('aij,ij->a', self._lift._modes, r)
                if _relative(direct-recorded_force, direct, recorded_force) > ALGEBRA:
                    raise TectonicsError('returned regional force does not reproduce physical virtual work')
            omega, resisting = np.zeros(len(self._b)), np.zeros(len(self._b))
            omega[self._a], resisting[self._a] = pair, regional_pair
            if self._global_basis is None:
                omega[self._other] = self._other_base-self._other_response@pair
            else:
                omega = self._global_basis@q
            if self._current_background is not None:
                from .integration_wall_measures import _decode
                limit = _decode(self._current_background['angular_rate_l2_bound_s_inv'])
                if sum(Fraction(float(v))**2 for v in omega) > limit**2:
                    raise TectonicsError('solved rate exceeds the declared current-pose virtual-work error domain')
            exterior_force = self._matrix@omega
            residual = exterior_force+resisting-self._b
            other_projected = lambda v: v if self._other_basis is None else self._other_basis.T@v
            if self._global_basis is None:
                projected = lambda v: np.r_[self._lift._basis.T@v[self._a], other_projected(v[self._other])]
            else:
                projected = lambda v: self._global_basis.T@v
            admissible = projected(residual)
            force_relative = _relative(admissible, projected(exterior_force), projected(resisting), projected(self._b))
            # Standard finite dot-product bound for the existing BLAS
            # matrix product, then the two residual additions and basis
            # projection. Retain the absolute residual independently.
            eps = np.finfo(float).eps
            gamma = (len(omega)+2)*eps/(1-(len(omega)+2)*eps)
            dot_error = gamma*(np.abs(self._matrix)@np.abs(omega))
            reaction_error = np.zeros_like(resisting); reaction_error[self._a] = pair_error
            residual_error = dot_error+reaction_error+4*eps*(np.abs(exterior_force)+np.abs(resisting)+np.abs(self._b))
            projection_error = (k+7)*eps*np.abs(self._lift._basis.T)@np.abs(residual[self._a])
            other_error = residual_error[self._other]
            if self._other_basis is not None:
                absolute_basis = np.abs(self._other_basis.T)
                other_error = (absolute_basis@other_error+
                    (len(self._other)+2)*eps*(absolute_basis@np.abs(residual[self._other])))
            if self._global_basis is None:
                bounds = np.r_[np.abs(self._lift._basis.T)@residual_error[self._a]+projection_error, other_error]
            else:
                absolute_basis = np.abs(self._global_basis.T)
                bounds = (absolute_basis@residual_error+
                    (len(omega)+2)*eps*(absolute_basis@np.abs(residual)))
            algebra_bound = float(np.max(np.nextafter(bounds, math.inf)))
            force_relative = _accounted_relative(admissible, bounds,
                projected(exterior_force), projected(resisting), projected(self._b))
            if force_relative > ALGEBRA:
                raise TectonicsError('coupled global torque equations exceed the existing D1 algebra gate')
            # Reaction needed to enforce the declared constraint. At full rank it
            # is just the retained numerical residual, not an external force.
            constrained = self._lift._basis.shape[1] < 6 or self._other_basis is not None or self._global_basis is not None
            constraint = residual if constrained else np.zeros_like(residual)
            boundary_work = math.fsum(float(v) for v in (actual*r).flat)
            plate_work = math.fsum(float(v) for v in pair*regional_pair)
            work_relative = _relative(boundary_work-plate_work, boundary_work, plate_work,
                                      np.sum(np.abs(actual*r)))
            if work_relative > WORK:
                raise TectonicsError('plate/regional work conjugacy exceeds the existing native work gate')
            from .integration_differential_trace import DifferentialPlateBoundaryLift
            trace_account = (self._lift.trace_account(pair.reshape(2, 3), r)
                             if type(self._lift) is DifferentialPlateBoundaryLift else None)
            reservoir_work = None
            if self._differential_pressure is not None:
                current = self._differential_pressure['forcing']
                reservoir_work = _reservoir_pressure_work(self._lift._trace._native, u,
                    current['reservoir_pressure'], self._budget)
            arrays = dict(omega_rad_s=omega.reshape(-1, 3), regional_resisting_torque_n_m=resisting.reshape(-1, 3),
                constraint_torque_n_m=constraint.reshape(-1, 3), torque_equation_residual_n_m=residual.reshape(-1, 3),
                admissible_torque_residual=admissible, angular_rate_basis=self._lift._basis,
                physical_boundary_position_m=self._lift._points, native_generalized_rates_s_inv=q)
            exterior_constraint_account = None
            global_constraint_account = None
            if self._global_basis is not None:
                arrays['global_angular_rate_basis'] = self._global_basis
                # This includes internal reaction transfer between linked
                # plates, not just transverse-pole constraint reactions.
                work = math.fsum(float(v) for v in omega*constraint)
                scale = math.fsum(abs(float(v)) for v in omega*(np.abs(exterior_force)+np.abs(resisting)+np.abs(self._b)))
                if _relative(work, scale) > WORK:
                    raise TectonicsError('global angular constraint does nonzero admissible virtual work')
                global_constraint_account = dict(work_w=work, work_operand_sum_w=scale,
                    projected_torque_residual_n_m=admissible.tolist(),
                    scope='declared global kinematic family; linked-plate reactions retained; no heat')
            if self._other_basis is not None:
                arrays['exterior_angular_rate_basis'] = self._other_basis
                external_constraint = np.zeros_like(residual)
                external_constraint[self._other] = residual[self._other]
                arrays['exterior_constraint_torque_n_m'] = external_constraint.reshape(-1, 3)
                # This is a physical constraint, not heat. Its admissible work
                # is zero up to the already checked projected torque residual.
                work = math.fsum(float(v) for v in omega*external_constraint)
                scale = math.fsum(abs(float(v)) for v in omega*(np.abs(exterior_force)+np.abs(resisting)+np.abs(self._b)))
                if _relative(work, scale) > WORK:
                    raise TectonicsError('exterior angular constraint does nonzero admissible virtual work')
                exterior_constraint_account = dict(work_w=work, work_operand_sum_w=scale,
                    projected_torque_residual_n_m=other_projected(residual[self._other]).tolist(),
                    scope='declared physical exterior subspace; no heat and no general pole-evolution claim')
            if datum_account is not None:
                datum_torque = np.zeros_like(resisting); datum_torque[self._a] = datum_pair
                free_torque = np.zeros_like(resisting); free_torque[self._a] = free_pair
                arrays['pressure_datum_constraint_torque_n_m'] = datum_torque.reshape(-1, 3)
                arrays['datum_free_regional_resisting_torque_n_m'] = free_torque.reshape(-1, 3)
            exchange = RegionalMechanicalSnapshot(dict(schema=SCHEMA+'.result', driving=definition,
                native_result_id=mechanical.result_id, native_plan_id=record['plan_id'],
                parent_state_id=parent_state_id, time_s=time_s, constrained=constrained,
                algebra_relative_residual=force_relative, virtual_work_relative_residual=work_relative,
                regional_boundary_work_w=boundary_work, plate_resisting_work_w=plate_work,
                exterior_resistance_work_w=float(omega@exterior_force),
                external_driving_work_w=float(omega@self._b),
                constraint_work_w=float(omega@constraint),
                algebra_absolute_residual_n_m=float(np.max(np.abs(admissible))),
                algebra_roundoff_bound_n_m=algebra_bound,
                native_force_absolute_residual_j=float(np.max(np.abs(mechanical.array('generalized_force_residual_j')))),
                **({} if datum_account is None else dict(pressure_datum_account=datum_account,
                    pressure_datum_constraint_work_w=float(pair@datum_pair))),
                **({} if trace_account is None else dict(differential_trace_account=trace_account)),
                **({} if reservoir_work is None else dict(reservoir_pressure_work=reservoir_work)),
                **({} if exterior_constraint_account is None else dict(exterior_constraint_account=exterior_constraint_account)),
                **({} if global_constraint_account is None else dict(global_constraint_account=global_constraint_account)),
                sign='M omega + regional resisting torque = b + constraint torque',
                heat='none booked here; exterior resistance is not regional internal heat',
                source_status='WORKING NON-CANON', scientific_acceptance=False), arrays)
            return PlateRegionalResult(mechanical, exchange)

    def solve(self, native, *, parent_state_id, time_s, epoch_id, force_source, boundary_source,
              body_force_n_m3=0., traction_pa=None, cancel=None):
        """One convenience solve; evolution callers use coupling()/reconstruct()."""
        self.descriptor()
        if type(native) is not PreparedRegionalStokes3D or native._resource is not self._budget:
            raise TectonicsError('an actual native plan on the same budget is required')
        definition = native.descriptor()
        if (any(definition[k] != v for k, v in self._lift._geometry.items())
                or definition.get('pressure_reference') != self._lift._pressure_reference
                or definition['material_source'] != self._lift._material_source):
            raise TectonicsError('native plan geometry, pressure reference or actual material source differs')
        if self._viscous_only:
            if (np.any(np.asarray(body_force_n_m3) != 0) or
                    (traction_pa is not None and any(np.any(np.asarray(v) != 0) for v in traction_pa.values())) or
                    definition.get('pressure_reference', {}).get('load_partition') == 'full'):
                raise TectonicsError('viscous-only radial increment cannot add gravity, body force or physical traction')
        arguments = self._coupling()
        partition = ({} if 'pressure_reference_id' not in arguments else
                     {'pressure_reference_id': arguments['pressure_reference_id']})
        if 'natural_traction_binding' in arguments:
            partition['natural_traction_binding'] = arguments['natural_traction_binding']
        solved = native.solve_force_coupled(body_force_n_m3, 0.,
            {s: 0. for s in SIDES} if traction_pa is None else traction_pa,
            arguments['boundary_modes_m'], arguments['external_generalized_force_j'],
            arguments['external_resistance_j_s'], coupling_source=arguments['source'],
            parent_state_id=parent_state_id, time_s=time_s, epoch_id=epoch_id,
            force_source=force_source, boundary_source=boundary_source, cancel=cancel, **partition)
        return self.reconstruct(solved, parent_state_id=parent_state_id, time_s=time_s)

    def close(self):
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self.descriptor()
        return self

    def __exit__(self, *_):
        self.close()
